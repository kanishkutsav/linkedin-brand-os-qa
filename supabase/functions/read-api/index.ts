import { createClient, type SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.57.0";

type User = { id: number; email: string; role: string; display_name: string | null; linkedin_url: string | null };

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if (!supabaseUrl || !serviceRoleKey) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required");

const db = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
const ALLOWED_ROLES = new Set(["admin", "owner", "reviewer", "user"]);

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
async function tokenHash(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function authenticate(req: Request): Promise<User> {
  const header = req.headers.get("authorization") || "";
  if (!header.toLowerCase().startsWith("bearer ")) throw new Error("Authentication required");
  const hash = await tokenHash(header.slice(7).trim());
  const { data: session, error: se } = await db.from("auth_sessions").select("user_id, expires_at").eq("token_hash", hash).gt("expires_at", new Date().toISOString()).maybeSingle();
  if (se || !session) throw new Error("Authentication required");
  const { data: user, error: ue } = await db.from("auth_users").select("id, email, role, display_name, linkedin_url, is_active, is_whitelisted").eq("id", session.user_id).maybeSingle();
  if (ue || !user || !user.is_active || !user.is_whitelisted || !ALLOWED_ROLES.has(user.role)) throw new Error("Authentication required");
  return user as User;
}
function parseJson(value: unknown, fallback: unknown) { if (typeof value !== "string" || !value) return fallback; try { return JSON.parse(value); } catch { return fallback; } }

async function profileRead(user: User) {
  const { data: p, error } = await db.from("user_profiles").select("*").eq("id", user.id).maybeSingle(); if (error) throw error;
  const row = p || { id: user.id, display_name: user.display_name || "User", role: user.role };
  return { id: row.id, display_name: row.display_name, professional_title: row.professional_title ?? null, industry: row.industry ?? null, experience_years: row.experience_years ?? null, tone: row.tone ?? null, role: row.role || "owner" };
}
async function brandStatusRead(user: User) {
  const [{ data: m, error: me }, { data: posts, error: pe }, { data: p, error: pfe }] = await Promise.all([
    db.from("brand_memory").select("*").eq("profile_id", user.id).maybeSingle(),
    db.from("historical_posts").select("id, body, published_at, source, created_at").eq("profile_id", user.id).not("body", "is", null).neq("body", "").order("published_at", { ascending: false }).limit(100),
    db.from("user_profiles").select("display_name, professional_title, industry, experience_years, tone").eq("id", user.id).maybeSingle(),
  ]);
  if (me || pe || pfe) throw me || pe || pfe;
  const rows = posts || [], sourcePosts = rows.filter((x: any) => x.source === "user_import").slice(0, 10);
  const complete = Boolean(p?.professional_title?.trim() && p?.industry?.trim() && p?.tone?.trim() && p?.experience_years !== null && p?.experience_years !== undefined);
  const ready = Boolean(m?.status === "READY" && complete);
  return { status: ready ? "READY" : (m ? "NEEDS_INPUT" : "NOT_INITIALIZED"), ready, source_post_count: m?.source_post_count ?? rows.length, current_post_count: rows.length, summary: m?.summary ?? null, continuous_learning: true, historical_import_optional: true, last_updated: m?.updated_at ?? null, profile: p || { display_name: user.display_name || "User", professional_title: null, industry: null, experience_years: null, tone: null }, source_posts: sourcePosts.map((x: any) => ({ id: x.id, body: x.body, published_at: x.published_at, source: x.source })) };
}
async function brandMemoryRead(user: User) {
  const { data: m, error } = await db.from("brand_memory").select("*").eq("profile_id", user.id).maybeSingle(); if (error) throw error;
  if (!m) return { status: "NOT_INITIALIZED", source_post_count: 0 };
  return { id: m.id, status: m.status, version: m.version, summary: m.summary, identity: parseJson(m.identity_json, []), expertise: parseJson(m.expertise_json, []), themes: parseJson(m.themes_json, []), opinions: parseJson(m.opinions_json, []), experiences: parseJson(m.experiences_json, []), formats: parseJson(m.formats_json, []), patterns: parseJson(m.patterns_json, {}), voice: parseJson(m.voice_json, {}), source_post_count: m.source_post_count, initialized_at: m.initialized_at ? new Date(m.initialized_at).toISOString() : null, updated_at: m.updated_at ? new Date(m.updated_at).toISOString() : null };
}
async function sourcePostsRead(user: User) {
  const { data, error } = await db.from("historical_posts").select("id, body, published_at, source").eq("profile_id", user.id).eq("source", "user_import").order("created_at", { ascending: true }).limit(10); if (error) throw error;
  return { posts: (data || []).map((x: any) => ({ id: x.id, body: x.body, published_at: x.published_at, source: x.source })) };
}
async function contentScope(user: User) {
  const { data: items, error } = await db.from("content_items").select("id, title, topic, pillar, status, created_at").eq("profile_id", user.id); if (error) throw error;
  const ids = (items || []).map((x: any) => x.id); if (!ids.length) return { items: [], versions: [], approvals: [] };
  const { data: versions, error: ve } = await db.from("content_versions").select("id, content_id, body, created_at, version_number").in("content_id", ids); if (ve) throw ve;
  const vids = (versions || []).map((x: any) => x.id); if (!vids.length) return { items: items || [], versions: versions || [], approvals: [] };
  const { data: approvals, error: ae } = await db.from("approval_requests").select("id, content_version_id, action_type, status, reason, edited_body, approved_at, created_at, published_external_id, published_image_urn").in("content_version_id", vids); if (ae) throw ae;
  return { items: items || [], versions: versions || [], approvals: approvals || [] };
}
function counts(approvals: any[]) {
  const n = (s: string) => approvals.filter((a: any) => a.status === s).length;
  return { total: approvals.length, awaiting_approval: n("PENDING")+n("EDITED")+n("REGENERATED"), approved: n("APPROVED"), published: n("EXECUTED"), needs_review: n("EDITED")+n("REGENERATED"), rejected: n("REJECTED"), pending_filter: n("PENDING")+n("APPROVED")+n("PUBLISHING") };
}
async function dashboardRead(user: User) {
  const { items, versions, approvals } = await contentScope(user);
  const im = new Map(items.map((x: any) => [x.id, x])), vm = new Map(versions.map((x: any) => [x.id, x]));
  const active = approvals.filter((a: any) => ["PENDING","EDITED","REGENERATED","APPROVED","PUBLISHING","FAILED"].includes(a.status)).sort((a: any,b: any) => +new Date(b.created_at)-+new Date(a.created_at)).slice(0,200);
  const rejected = approvals.filter((a: any) => a.status==="REJECTED").sort((a: any,b: any) => +new Date(b.created_at)-+new Date(a.created_at)).slice(0,10);
  const published = approvals.filter((a: any) => a.status==="EXECUTED").sort((a: any,b: any) => +new Date(b.approved_at||b.created_at)-+new Date(a.approved_at||a.created_at)).slice(0,10);
  const unique = new Map<number, any>(); for (const a of [...active,...rejected,...published]) unique.set(a.id,a);
  const records = [...unique.values()].sort((a,b) => +new Date(b.created_at)-+new Date(a.created_at)).map((a: any) => { const v=vm.get(a.content_version_id), item=v?im.get(v.content_id):null; return { id:a.id, status:a.status==="FAILED"?"APPROVED":a.status, action_type:a.action_type, reason:a.reason || (a.status==="FAILED" ? "A previous LinkedIn publication attempt failed. The post is approved and ready to retry." : null), content:v?.body||"", title:item?.title||"", topic:item?.topic||"", approved_at:a.approved_at, created_at:a.created_at }; });
  return { pending_approvals: records, counts: counts(approvals) };
}
async function agentRead(user: User) {
  const { data, error } = await db.from("agent_runs").select("*").eq("user_id", user.id).order("started_at", { ascending:false }).limit(10); if (error) throw error;
  return { enabled:true, modes:{ daily_discovery:true, event_driven:true, scheduled_calendar:true }, recent_runs:(data||[]).map((r:any)=>({id:r.id,mode:r.mode,trigger:r.trigger,status:r.status,created_count:r.created_count,started_at:r.started_at,finished_at:r.finished_at,details:r.details})) };
}
async function researchRead(user: User) { const {data,error}=await db.from("content_opportunities").select("*").eq("profile_id",user.id).order("created_at",{ascending:false}).limit(20); if(error)throw error; return {opportunities:data||[]}; }
async function learningRead(user: User) {
  const {count: pending,error:pe}=await db.from("learning_events").select("id",{count:"exact",head:true}).eq("profile_id",user.id).eq("status","PENDING");
  const {count: memories,error:me}=await db.from("learning_memories").select("id",{count:"exact",head:true}).eq("profile_id",user.id);
  if(pe||me) throw pe||me; return {pending_events:pending||0,memory_count:memories||0};
}
async function analyticsRead(user: User) {
  const {items,approvals}=await contentScope(user);
  const {count:historical_posts,error:he}=await db.from("historical_posts").select("id",{count:"exact",head:true}).eq("profile_id",user.id); if(he)throw he;
  const pipeline={historical_posts:historical_posts||0,content_items:items.length,pending_approval:approvals.filter((a:any)=>["PENDING","EDITED","REGENERATED"].includes(a.status)).length,approved:approvals.filter((a:any)=>a.status==="APPROVED").length,published_via_brand_os:approvals.filter((a:any)=>a.status==="EXECUTED").length};
  const {data:connection,error:ce}=await db.from("linkedin_connections").select("access_token,token_expires_at").eq("user_id",user.id).maybeSingle(); if(ce)throw ce;
  if(!connection)return {pipeline,linkedin_performance:{available:false,authorization_required:true,message:"Connect LinkedIn first. Analytics requires the official Community Management member analytics permissions."}};
  if(connection.token_expires_at&&new Date(connection.token_expires_at)<=new Date())return {pipeline,linkedin_performance:{available:false,authorization_required:true,message:"Your LinkedIn connection has expired. Reconnect after analytics permissions are enabled."}};
  return {pipeline,linkedin_performance:{available:false,authorization_required:false,message:"LinkedIn analytics API execution remains staged for the Phase 4 QA cutover; the connection token stays server-side."}};
}
const handlers: Record<string,(u:User)=>Promise<unknown>>={profile:profileRead,"brand/status":brandStatusRead,"brand/memory":brandMemoryRead,"brand/source-posts":sourcePostsRead,"dashboard/approvals":dashboardRead,"agent/status":agentRead,"research/opportunities":researchRead,"learning/status":learningRead,"analytics/overview":analyticsRead};
Deno.serve(async(req)=>{ if(req.method!=="GET")return json({error:"Method not allowed"},405); const route=new URL(req.url).pathname.replace(/^\/read-api\/?/,"").replace(/^\/?/,""); const h=handlers[route]; if(!h)return json({error:"Not found"},404); try{return json(await h(await authenticate(req)));}catch(e){const m=e instanceof Error?e.message:"Read request failed"; if(m==="Authentication required")return json({error:m},401); console.error("read-api error",e); return json({error:"Read request failed"},500);}});
