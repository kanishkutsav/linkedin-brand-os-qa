import { createClient } from "https://esm.sh/@supabase/supabase-js@2.57.0";

type User={id:number;email:string;role:string;display_name:string|null;linkedin_url:string|null};
const url=Deno.env.get("SUPABASE_URL"), key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if(!url||!key)throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required");
const db=createClient(url,key,{auth:{persistSession:false,autoRefreshToken:false}});
const ROLES=new Set(["admin","owner","reviewer","user"]);
const AI_PHRASES=["in today's rapidly evolving","game-changer","unlock the power of","delve into","here's the thing","in conclusion","as we navigate","the future of","x is no longer"];

function out(data:unknown,status=200){return new Response(JSON.stringify(data),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});}
async function hash(s:string){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s));return Array.from(new Uint8Array(d)).map(x=>x.toString(16).padStart(2,"0")).join("");}
async function auth(req:Request):Promise<User>{
 const h=req.headers.get("authorization")||"";if(!h.toLowerCase().startsWith("bearer "))throw new Error("Authentication required");
 const token=h.slice(7).trim();if(!token)throw new Error("Authentication required");
 const th=await hash(token);
 const {data:s,error:se}=await db.from("auth_sessions").select("user_id,expires_at").eq("token_hash",th).gt("expires_at",new Date().toISOString()).maybeSingle();
 if(se||!s)throw new Error("Authentication required");
 const {data:u,error:ue}=await db.from("auth_users").select("id,email,role,display_name,linkedin_url,is_active,is_whitelisted").eq("id",s.user_id).maybeSingle();
 if(ue||!u||!u.is_active||!u.is_whitelisted||!ROLES.has(u.role))throw new Error("Authentication required");
 return u as User;
}
function guards(body:string){const issues:string[]=[];const text=(body||"").trim(),lower=text.toLowerCase();
 if(text.includes("—")||text.includes("–"))issues.push("Em/en dashes are not allowed in generated content.");
 if(text.includes(";"))issues.push("Semicolons are not allowed in generated content.");
 if(!text)issues.push("Content is empty.");else if(text.length<40)issues.push("Content is too short to be a usable LinkedIn post.");else if(text.length>3000)issues.push("Content exceeds the supported 3000-character review limit.");
 for(const p of AI_PHRASES)if(lower.includes(p))issues.push("Avoid generic phrase: "+p);
 if(/\b\d{2,3}%\b/.test(text)&&!(/https?:\/\/|source|according to|reported|data/.test(lower)))issues.push("Statistic-like claim detected without an obvious source marker.");
 if((text.match(/(?<!\w)#[A-Za-z0-9_]+/g)||[]).length>5)issues.push("Too many hashtags; keep the post focused.");
 if(/\b(very|really|truly)\s+(important|powerful|critical)\b/.test(lower))issues.push("Replace generic emphasis with a concrete observation.");
 return {passed:issues.length===0,risk:issues.length>=2?"high":issues.length?"medium":"low",issues};
}
async function ownedApproval(user:User,id:number){
 const {data,error}=await db.from("approval_requests").select("*, content_versions!inner(id,body,content_hash,version_number,content_items!inner(id,profile_id,title,topic,pillar,status))").eq("id",id).eq("content_versions.content_items.profile_id",user.id).maybeSingle();
 if(error||!data)throw new Error("Approval not found");return data as any;
}
async function idem(user:User,op:string,k:string){const {data}=await db.from("mutation_requests").select("response_json").eq("user_id",user.id).eq("operation",op).eq("idempotency_key",k).maybeSingle();return data?.response_json?JSON.parse(data.response_json):null;}
async function saveIdem(user:User,op:string,k:string,response:unknown){const {error}=await db.from("mutation_requests").insert({user_id:user.id,operation:op,idempotency_key:k,response_json:JSON.stringify(response)});if(error&&!error.message.toLowerCase().includes("duplicate"))throw error;}
async function learningEvent(user:User,eventType:string,sourceType:string,sourceId:string,content:string,metadata:Record<string,unknown>={}){
 const {data,error}=await db.from("learning_events").insert({profile_id:user.id,event_type:eventType,source_type:sourceType,source_id:sourceId,content,metadata_json:JSON.stringify(metadata),status:"PENDING",attempts:0}).select("id").single();if(error)throw error;return data.id;
}
async function createDraft(user:User,body:any){
 const {data:p,error:pe}=await db.from("user_profiles").select("*").eq("id",user.id).maybeSingle();if(pe)throw pe;
 if(!p?.professional_title||!p?.industry||!p?.tone||p.experience_years===null||p.experience_years===undefined)throw new Error("Complete Professional Title, Industry, Desired Tone and Years of Experience before creating content.");
 const {data:m,error:me}=await db.from("brand_memory").select("status").eq("profile_id",user.id).maybeSingle();if(me)throw me;if(!m||m.status!=="READY")throw new Error("Complete Brand DNA setup before creating content.");
 const clean=String(body.body||""),digest=await hash(clean);
 const {data:cv,error:ce}=await db.from("content_versions").select("id").eq("content_hash",digest).limit(1);if(ce)throw ce;if(cv?.length)throw new Error("This exact content already exists in your brand memory.");
 const {data:hp,error:he}=await db.from("historical_posts").select("id").eq("profile_id",user.id).eq("content_hash",digest).limit(1);if(he)throw he;if(hp?.length)throw new Error("This exact content already exists in your brand memory.");
 const g=guards(clean);
 const {data:item,error:ie}=await db.from("content_items").insert({profile_id:user.id,title:String(body.title||""),topic:String(body.topic||""),pillar:String(body.pillar||"Expertise"),status:g.passed?"AWAITING_APPROVAL":"EDIT_REQUIRED"}).select("id").single();if(ie)throw ie;
 const {data:v,error:ve}=await db.from("content_versions").insert({content_id:item.id,body:clean,content_hash:digest,version_number:1}).select("id").single();if(ve)throw ve;
 let approvalId:null|number=null;
 if(g.passed){const {data:a,error:ae}=await db.from("approval_requests").insert({content_version_id:v.id,action_type:"PUBLISH_POST",status:"PENDING",expires_at:new Date(Date.now()+Number(Deno.env.get("APPROVAL_TTL_MINUTES")||120)*60000).toISOString()}).select("id").single();if(ae)throw ae;approvalId=a.id;}
 await learningEvent(user,"CONTENT_DRAFT","manual_content",String(v.id),clean,{title:body.title||"",topic:body.topic||"",guard_passed:g.passed});
 return {content_id:item.id,version_id:v.id,guard:g,approval_id:approvalId};
}
async function mutateApproval(user:User,id:number,op:string,body:any){
 const a=await ownedApproval(user,id),v=a.content_versions,item=v.content_items;
 if(op==="approve"){
  if(a.status==="APPROVED")return {id:a.id,status:a.status,approval_hash:a.approval_hash,approved_at:a.approved_at,message:"Approved. The content is now locked and ready for execution."};
  if(["EXECUTED","PUBLISHING"].includes(a.status))throw new Error("This post has already been approved and is locked.");
  if(!["PENDING","EDITED","REGENERATED"].includes(a.status))throw new Error("Approval is not in an approvable state");
  if(a.expires_at&&new Date(a.expires_at)<=new Date()){await db.from("approval_requests").update({status:"EXPIRED"}).eq("id",id);throw new Error("Approval has expired");}
  const g=guards(v.body);if(!g.passed)throw new Error("Approval blocked by guardrails: "+g.issues.join("; "));
  const ah=await hash(String(id)+":"+v.content_hash),now=new Date().toISOString();
  const {error:e}=await db.from("approval_requests").update({status:"APPROVED",approval_hash:ah,approved_at:now}).eq("id",id);if(e)throw e;
  await db.from("content_items").update({status:"APPROVED"}).eq("id",item.id);
  await db.from("audit_logs").insert({event_type:"APPROVAL_GRANTED",actor:"user",payload:"approval="+id});
  await db.from("feedback_entries").insert({approval_id:id,content_version_id:v.id,action:"APPROVED",reason:"User approved the content.",payload:"approval="+id});
  await learningEvent(user,"CONTENT_APPROVED","approval",String(id),v.body,{reason:"human_approval"});
  return {id,status:"APPROVED",approval_hash:ah,approved_at:now,message:"Approved. The content is now locked and ready for execution."};
 }
 if(op==="edit"){
  if(!["PENDING","EDITED","REGENERATED"].includes(a.status))throw new Error("Approval is not editable in its current state");
  if(a.expires_at&&new Date(a.expires_at)<=new Date()){await db.from("approval_requests").update({status:"EXPIRED"}).eq("id",id);throw new Error("Approval has expired");}
  const edited=String(body.edited_body||"").trim(),g=guards(edited);if(!g.passed)throw new Error("Edit blocked by guardrails: "+g.issues.join("; "));
  const digest=await hash(edited);
  const {data:du,error:de}=await db.from("content_versions").select("id").eq("content_hash",digest).neq("id",v.id).limit(1);if(de)throw de;if(du?.length)throw new Error("This exact content already exists in your brand memory.");
  const {data:dh,error:dhe}=await db.from("historical_posts").select("id").eq("profile_id",user.id).eq("content_hash",digest).limit(1);if(dhe)throw dhe;if(dh?.length)throw new Error("This exact content already exists in your brand memory.");
  const reason=String(body.reason||"").trim()||"Content was edited by the human reviewer.",next=Number(v.version_number||0)+1;
  const {error:ve}=await db.from("content_versions").update({body:edited,content_hash:digest,version_number:next}).eq("id",v.id);if(ve)throw ve;
  const {error:ae}=await db.from("approval_requests").update({status:"EDITED",edited_body:edited,reason}).eq("id",id);if(ae)throw ae;
  await db.from("feedback_entries").insert({approval_id:id,content_version_id:v.id,action:"EDITED",reason,payload:edited});
  await db.from("audit_logs").insert({event_type:"APPROVAL_EDITED",actor:"user",payload:"approval="+id});
  await learningEvent(user,"CONTENT_EDITED","approval_edit",String(id)+":"+next,edited,{reason});
  return {id,status:"EDITED",reason,edited_body:edited};
 }
 if(op==="reject"){
  if(a.status==="EXECUTED")throw new Error("Published content cannot be rejected from the approval workflow.");
  const reason=String(body.reason||"").trim()||"Rejected by human reviewer.";
  const {error:ae}=await db.from("approval_requests").update({status:"REJECTED",reason}).eq("id",id);if(ae)throw ae;
  await db.from("content_items").update({status:"REJECTED"}).eq("id",item.id);
  await db.from("feedback_entries").insert({approval_id:id,content_version_id:v.id,action:"REJECTED",reason,payload:"rejected"});
  await db.from("audit_logs").insert({event_type:"APPROVAL_REJECTED",actor:"user",payload:"approval="+id});
  await learningEvent(user,"CONTENT_REJECTED","approval_rejection",String(id),reason,{draft:v.body.slice(0,6000),reason});
  return {id,status:"REJECTED",reason};
 }
 throw new Error("Unsupported mutation");
}
Deno.serve(async(req)=>{
 if(req.method!=="POST")return out({error:"Method not allowed"},405);
 try{
  const user=await auth(req),path=new URL(req.url).pathname.replace(/^\/write-api\/?/,"").replace(/^\/?/,""),body=await req.json().catch(()=>({}));
  const op=path.startsWith("approvals/")?path.split("/")[1]:path,id=path.startsWith("approvals/")?Number(path.split("/")[2]):0,k=req.headers.get("X-Idempotency-Key")||"";
  if(["create-draft","learning-thought","approve","edit","reject"].includes(op)&&!k)return out({error:"X-Idempotency-Key is required for retry-safe mutations"},400);
  if(k){const prior=await idem(user,op,k);if(prior)return out(prior);}
  let result:any;
  if(op==="create-draft")result=await createDraft(user,body);
  else if(op==="learning-thought"){const content=String(body.content||"").trim();if(content.length<10)throw new Error("Write a little more so Brand OS has a useful idea to learn from.");if(content.length>20000)throw new Error("Thoughts are limited to 20,000 characters.");const eid=await learningEvent(user,"USER_THOUGHT","manual_thought","",content,{topic:String(body.topic||"").slice(0,300),title:String(body.title||"").slice(0,200)});result={saved:true,event_id:eid};}
  else if(["approve","edit","reject"].includes(op))result=await mutateApproval(user,id,op,body);
  else return out({error:"Not found"},404);
  if(k)await saveIdem(user,op,k,result);
  return out(result);
 }catch(e){const m=e instanceof Error?e.message:"Mutation failed";if(m==="Authentication required")return out({error:m},401);console.error("write-api error",e);return out({error:m},400);}
});
