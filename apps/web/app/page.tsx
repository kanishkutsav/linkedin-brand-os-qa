'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity, ArrowUpRight, BarChart3, BrainCircuit, Check, ChevronRight, CircleCheck,
  Clock3, Command, Download, ExternalLink, FileText, Gauge, Globe2, LayoutDashboard, Link2,
  LogOut, MoreHorizontal, Pencil, Plus, RefreshCw, RotateCcw, Search, Settings,
  ShieldCheck, Sparkles, Target, TrendingUp, UserRound, WandSparkles, X, Zap
} from 'lucide-react';

const API_BASE = typeof window !== 'undefined' && window.location.hostname === 'localhost' ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') : '';
const STORAGE_KEY = 'brand-os-token';

function getApiError(data: any, fallback: string) {
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item: any) => item?.msg || String(item)).join('; ');
  if (typeof data?.message === 'string') return data.message;
  return fallback;
}

type ApprovalStatus = 'PENDING' | 'EDITED' | 'REGENERATED' | 'APPROVED' | 'PUBLISHING' | 'REJECTED' | 'EXECUTED';
type ApprovalItem = { id: number; status: ApprovalStatus; action_type: string; reason: string | null; content: string; title?: string; topic?: string; approved_at?: string | null; created_at?: string };
type Profile = { display_name: string; role?: string };
type LinkedInStatus = { connected: boolean; name?: string | null; email?: string | null; expires_at?: string | null };
type BrandStatus = {
  ready: boolean; status: string; source_post_count: number; current_post_count?: number;
  continuous_learning?: boolean; historical_import_optional?: boolean; last_updated?: string | null;
  summary?: string | null;
  profile?: { display_name?: string; professional_title?: string | null; industry?: string | null; experience_years?: number | null; tone?: string | null };
};
type Opportunity = {
  id: number; title: string; topic: string; angle: string; pillar: string; format?: string; objective?: string;
  total_score: number; scores: Record<string, number>; rationale?: string;
  evidence?: { summary?: string; why_now?: string; source_hints?: string[]; grounding_queries?: string[] };
  source_ids?: number[]; sources?: { title?: string; url?: string; domain?: string }[];
};
type Tab = 'Dashboard' | 'Research' | 'Content' | 'LinkedIn Posts' | 'Analytics' | 'Brand DNA';

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

const nav = [
  ['Dashboard', LayoutDashboard, 'Command center'],
  ['Research', Search, 'Find opportunities'],
  ['Content', FileText, 'Draft & refine'],
  ['LinkedIn Posts', ExternalLink, 'Published posts'],
  ['Analytics', BarChart3, 'Performance'],
  ['Brand DNA', Settings, 'Brand DNA'],
] as const;

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile>({ display_name: 'User', role: 'owner' });
  const [linkedin, setLinkedin] = useState<LinkedInStatus>({ connected: false });
  const [brand, setBrand] = useState<BrandStatus>({ ready: false, status: 'NOT_INITIALIZED', source_post_count: 0 });
  const [brandTitle, setBrandTitle] = useState('');
  const [brandIndustry, setBrandIndustry] = useState('');
  const [brandExperienceYears, setBrandExperienceYears] = useState<number | ''>('');
  const [brandTone, setBrandTone] = useState('');
  const [historicalPostEntries, setHistoricalPostEntries] = useState<string[]>([]);
  const [brandEditing, setBrandEditing] = useState(false);
  const [analytics, setAnalytics] = useState<any>(null);
  const [draftLanguage, setDraftLanguage] = useState('');
  const [isImproving, setIsImproving] = useState(false);
  const [improvementProgress, setImprovementProgress] = useState(0);
  const [improvementNotes, setImprovementNotes] = useState<string[]>([]);
  const [isBuildingBrand, setIsBuildingBrand] = useState(false);
  const [queue, setQueue] = useState<ApprovalItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<'PENDING' | 'NEEDS_REVIEW' | 'EXECUTED' | 'REJECTED'>('PENDING');
  const [searchTerm, setSearchTerm] = useState('');
  const [editedBody, setEditedBody] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeTtl, setNoticeTtl] = useState(4500);
  const [isBusy, setIsBusy] = useState(false);
  const [busyAction, setBusyAction] = useState<'approve' | 'edit' | 'reject' | 'regenerate' | 'execute' | null>(null);
  const [operationProgress, setOperationProgress] = useState(0);
  const [operationStage, setOperationStage] = useState('');
  const [tab, setTab] = useState<Tab>('Dashboard');
  const [draftTitle, setDraftTitle] = useState('');
  const [draftTopic, setDraftTopic] = useState('');
  const [draftBody, setDraftBody] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgress, setGenerationProgress] = useState(0);
  const [generationStage, setGenerationStage] = useState('');
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [researchFocus, setResearchFocus] = useState('');
  const [isResearching, setIsResearching] = useState(false);
  const [researchProgress, setResearchProgress] = useState(0);
  const [researchStage, setResearchStage] = useState('');
  const [moreOpen, setMoreOpen] = useState(false);
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [isStandalone, setIsStandalone] = useState(false);
  const [showIosInstallGuide, setShowIosInstallGuide] = useState(false);
  const [loading, setLoading] = useState(false);
  const [learningStatus, setLearningStatus] = useState({ pending_events: 0, memory_count: 0 });
  const [dashboardCounts, setDashboardCounts] = useState({
    total: 0, awaiting_approval: 0, approved: 0, published: 0,
    needs_review: 0, rejected: 0, pending_filter: 0,
  });
  const [savingThought, setSavingThought] = useState(false);

  const headers = (authToken = token) => authToken ? { Authorization: `Bearer ${authToken}` } : {};

  useEffect(() => {
    const standalone = window.matchMedia('(display-mode: standalone)').matches || (window.navigator as any).standalone === true;
    setIsStandalone(standalone);

    const handleBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as BeforeInstallPromptEvent);
    };
    const handleAppInstalled = () => {
      setInstallPrompt(null);
      setIsStandalone(true);
      setMoreOpen(false);
      setNotice('Brand OS was added to your device.');
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => undefined);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), noticeTtl);
    return () => window.clearTimeout(timer);
  }, [notice, noticeTtl]);

  useEffect(() => {
    if (!isGenerating) {
      setGenerationProgress(0);
      setGenerationStage('');
      return;
    }
    setGenerationProgress(10);
    setGenerationStage('Preparing your Brand DNA…');
    const timers = [
      window.setTimeout(() => { setGenerationProgress(28); setGenerationStage('Generating with AI…'); }, 450),
      window.setTimeout(() => { setGenerationProgress(62); setGenerationStage('Shaping the draft around your voice…'); }, 1800),
    ];
    return () => timers.forEach(window.clearTimeout);
  }, [isGenerating]);

  useEffect(() => {
    if (!isImproving) {
      setImprovementProgress(0);
      return;
    }
    setImprovementProgress(12);
    const timer = window.setTimeout(() => setImprovementProgress(58), 700);
    return () => window.clearTimeout(timer);
  }, [isImproving]);

  useEffect(() => {
    if (!isResearching) {
      setResearchProgress(0);
      setResearchStage('');
      return;
    }
    setResearchProgress(8);
    setResearchStage('Connecting to live sources…');
    const timers = [
      window.setTimeout(() => { setResearchProgress(24); setResearchStage('Collecting current public sources…'); }, 700),
      window.setTimeout(() => { setResearchProgress(46); setResearchStage('Cross-checking and deduplicating evidence…'); }, 1800),
      window.setTimeout(() => { setResearchProgress(68); setResearchStage('Matching evidence to your Brand DNA…'); }, 3000),
      window.setTimeout(() => { setResearchProgress(82); setResearchStage('Ranking opportunities…'); }, 4800),
    ];
    return () => timers.forEach(window.clearTimeout);
  }, [isResearching]);

useEffect(() => {
    if (!busyAction) {
      setOperationProgress(0);
      setOperationStage('');
      return;
    }
    setOperationProgress(12);
    setOperationStage(busyAction === 'regenerate' ? 'Regenerating with your feedback…' : 'Processing your request…');
    const timer = window.setTimeout(() => {
      setOperationProgress(62);
      setOperationStage(busyAction === 'regenerate' ? 'Running guardrails and creating the new version…' : 'Applying the change…');
    }, 900);
    return () => window.clearTimeout(timer);
  }, [busyAction]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('linkedin_code');
    const oauthNonce = params.get('oauth_nonce');
    const savedToken = window.localStorage.getItem(STORAGE_KEY);
    if (code) {
      const expectedNonce = window.localStorage.getItem('brand-os-oauth-nonce');
      window.history.replaceState({}, document.title, window.location.pathname);
      if (!expectedNonce || !oauthNonce || expectedNonce !== oauthNonce) {
        window.localStorage.removeItem('brand-os-oauth-nonce');
        setError('LinkedIn sign-in could not be verified in this browser. Please start the connection again.');
        return;
      }
      fetch(`${API_BASE}/api/auth/linkedin/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, oauth_nonce: oauthNonce }),
      }).then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(getApiError(data, 'LinkedIn connection failed'));
        window.localStorage.setItem(STORAGE_KEY, data.token);
        window.localStorage.removeItem('brand-os-oauth-nonce');
        setToken(data.token);
        setNotice('LinkedIn account connected successfully.');
      }).catch((e) => {
        window.localStorage.removeItem('brand-os-oauth-nonce');
        setError(e instanceof Error ? e.message : 'LinkedIn connection failed');
      });
      return;
    }
    if (savedToken) setToken(savedToken);
  }, []);

  const fetchData = async (authToken: string | null = token) => {
    if (!authToken) return;
    setLoading(true);
    try {
      // Load the core workspace first. Optional panels must never block the
      // dashboard/Brand DNA from appearing.
      const [profileRes, approvalsRes, linkedinRes, brandRes] = await Promise.all([
        fetch(`${API_BASE}/api/auth/me`, { headers: headers(authToken) }),
        fetch(`${API_BASE}/api/dashboard/approvals`, { headers: headers(authToken) }),
        fetch(`${API_BASE}/api/linkedin/status`, { headers: headers(authToken) }),
        fetch(`${API_BASE}/api/brand/status`, { headers: headers(authToken) }),
      ]);
      if (profileRes.status === 401 || approvalsRes.status === 401) {
        window.localStorage.removeItem(STORAGE_KEY);
        setToken(null); setQueue([]); setLinkedin({ connected: false });
        throw new Error('Your session expired. Please sign in with LinkedIn again.');
      }
      if (!profileRes.ok || !approvalsRes.ok) throw new Error('Unable to load dashboard data.');

      const profileJson = await profileRes.json();
      const approvalsJson = await approvalsRes.json();
      setProfile({ display_name: profileJson.display_name || 'User', role: profileJson.role || 'owner' });
      setLinkedin(linkedinRes.ok ? await linkedinRes.json() : { connected: false });

      let brandJson = brandRes.ok ? await brandRes.json() : { ready: false, status: 'NOT_INITIALIZED', source_post_count: 0 };

      setBrand(brandJson);
      const p = brandJson.profile || {};
      setBrandTitle(p.professional_title || '');
      setBrandIndustry(p.industry || '');
      setBrandExperienceYears(typeof p.experience_years === 'number' ? p.experience_years : '');
      setBrandTone(p.tone || '');

      // Brand status now carries the frozen source-post snapshot, so Brand DNA
      // does not depend on a second request just to display the user's posts.
      const sourcePosts = (brandJson.source_posts || [])
        .map((item: any) => item.body)
        .filter((body: any) => typeof body === 'string' && body.trim());
      if (sourcePosts.length) setHistoricalPostEntries(sourcePosts.slice(0, 10));

      const nextQueue: ApprovalItem[] = (approvalsJson.pending_approvals || []).map((item: any) => ({
        id: item.id, status: item.status, action_type: item.action_type, reason: item.reason, content: item.content || '',
        title: item.title || '', topic: item.topic || '', approved_at: item.approved_at || null, created_at: item.created_at,
      }));
      setQueue(nextQueue);
      setDashboardCounts({
        total: Number(approvalsJson.counts?.total ?? 0),
        awaiting_approval: Number(approvalsJson.counts?.awaiting_approval ?? 0),
        approved: Number(approvalsJson.counts?.approved ?? 0),
        published: Number(approvalsJson.counts?.published ?? 0),
        needs_review: Number(approvalsJson.counts?.needs_review ?? 0),
        rejected: Number(approvalsJson.counts?.rejected ?? 0),
        pending_filter: Number(approvalsJson.counts?.pending_filter ?? 0),
      });
      if (nextQueue.length && !nextQueue.some((i) => i.id === selectedId)) setSelectedId(nextQueue[0].id);

      setLoading(false);

      // Optional workspace panels load independently. A slow research feed or
      // analytics query must not blank/freeze the main workspace.
      void Promise.all([
        fetch(`${API_BASE}/api/research/opportunities`, { headers: headers(authToken) }),
        fetch(`${API_BASE}/api/analytics/overview`, { headers: headers(authToken) }),
        fetch(`${API_BASE}/api/learning/status`, { headers: headers(authToken) }),
      ]).then(async ([opportunityRes, analyticsRes, learningRes]) => {
        const opportunityJson = opportunityRes.ok ? await opportunityRes.json() : { opportunities: [] };
        setOpportunities(opportunityJson.opportunities || []);
        const analyticsJson = analyticsRes.ok ? await analyticsRes.json() : null;
        setAnalytics(analyticsJson);
        if (learningRes.ok) setLearningStatus(await learningRes.json());
      }).catch(() => {
        // Optional panels are allowed to fail without affecting the core workspace.
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load dashboard data');
      setLoading(false);
    }
  };
  useEffect(() => { fetchData(token); }, [token]);
  useEffect(() => {
    const selected = queue.find((item) => item.id === selectedId);
    if (!selected) return;
    setEditedBody(selected.content || '');
    const savedFeedback = window.localStorage.getItem(`brand-os-regeneration-feedback:${selected.id}`);
    setReviewNote(savedFeedback || '');
  }, [selectedId, queue]);

  const filteredQueue = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return queue.filter((item) => {
      const normalizedStatus = String(item.status || '').trim().toUpperCase();
      const statusMatch = statusFilter === 'PENDING'
        ? ['PENDING', 'APPROVED', 'PUBLISHING'].includes(normalizedStatus)
        : statusFilter === 'NEEDS_REVIEW'
          ? ['EDITED', 'REGENERATED'].includes(normalizedStatus)
          : normalizedStatus === statusFilter;
      const haystack = `${item.action_type} ${item.content} ${item.reason || ''}`.toLowerCase();
      return statusMatch && (!query || haystack.includes(query));
    });
  }, [queue, searchTerm, statusFilter]);

  useEffect(() => {
    if (!filteredQueue.length) {
      setSelectedId(null);
      return;
    }
    if (!filteredQueue.some((item) => item.id === selectedId)) {
      setSelectedId(filteredQueue[0].id);
    }
  }, [filteredQueue, selectedId]);

  const selectedApproval = queue.find((item) => item.id === selectedId) ?? null;
  const summary = {
    pending: dashboardCounts.awaiting_approval,
    reviewed: dashboardCounts.approved,
    rejected: dashboardCounts.rejected,
    executed: dashboardCounts.published,
  };

  const initials = (profile.display_name || 'User').split(' ').map((x) => x[0]).slice(0, 2).join('').toUpperCase();
  const closeMore = () => setMoreOpen(false);
  const isIosDevice = () => /iphone|ipad|ipod/i.test(window.navigator.userAgent) || (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  const installBrandOS = async () => {
    if (isStandalone) return;
    if (installPrompt) {
      const prompt = installPrompt;
      setInstallPrompt(null);
      await prompt.prompt();
      const choice = await prompt.userChoice;
      if (choice.outcome === 'accepted') setNotice('Installing Brand OS…');
      return;
    }
    if (isIosDevice()) {
      setMoreOpen(false);
      setShowIosInstallGuide(true);
      return;
    }
    setNotice('Use your browser menu to install Brand OS or add it to your home screen.');
  };
  const connectLinkedIn = () => {
    const nonce = window.crypto?.randomUUID?.() || (Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
    window.localStorage.setItem('brand-os-oauth-nonce', nonce);
    window.location.href = '/api/auth/linkedin/start?browser_nonce=' + encodeURIComponent(nonce);
  };
  const cancelBrandEdit = async () => { await fetchData(); setBrandEditing(false); };
  const logout = async () => {
    try {
      if (token) {
        await fetch(API_BASE + '/api/auth/logout', { method: 'POST', headers: headers(token) });
      }
    } finally {
      window.localStorage.removeItem(STORAGE_KEY);
      setToken(null); setQueue([]); setLinkedin({ connected: false });
    }
  };
  const go = (next: Tab) => {
    setMoreOpen(false);
    if (!brand.ready && next !== 'Brand DNA') {
      setTab('Brand DNA');
      setNotice('Before using the workspace, complete your Brand DNA setup once.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    setTab(next);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const requireBrand = (actionLabel: string) => {
    if (brand.ready) return true;
    go('Brand DNA');
    setError('Brand DNA is not set up yet. Before ' + actionLabel + ', complete your Brand DNA details and add 3–10 previous LinkedIn posts to calibrate your writing voice.');
    return false;
  };

  const runApprovalAction = async (action: 'approve' | 'edit' | 'reject' | 'regenerate' | 'execute', payload?: Record<string, string> | File | null) => {
    if (!selectedApproval || !token) return;
    if (action === 'regenerate' && !requireBrand('regenerating content')) return;
    if (action === 'regenerate' && !reviewNote.trim()) {
      setError('Add feedback for the regeneration first. The Regenerate button will stay disabled until you do.');
      return;
    }
    setIsBusy(true); setBusyAction(action); setError(null); setNotice(null);
    if (action === 'approve') {
      setOperationProgress(20);
      setOperationStage('Locking the approved version…');
    } else if (action === 'execute') {
      setOperationProgress(20);
      setOperationStage('Preparing LinkedIn publication…');
    }
    try {
      const isExecute = action === 'execute';
      const requestInit: RequestInit = {
        method: 'POST',
        headers: isExecute ? headers() : { ...headers(), 'Content-Type': 'application/json' },
        body: isExecute
          ? (() => {
              const form = new FormData();
              if (payload instanceof File) form.append('image', payload);
              return form;
            })()
          : JSON.stringify(payload || {}),
      };
      const res = await fetch(`${API_BASE}/api/approvals/${selectedApproval.id}/${action}`, requestInit);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, `Action failed: ${action}`));
      if (action === 'execute' && data.published === false) {
        throw new Error(data.message || 'Execution was not completed.');
      }
      if (action === 'regenerate') {
        window.localStorage.removeItem(`brand-os-regeneration-feedback:${selectedApproval.id}`);
        setReviewNote('');
      }
      if (action === 'approve') {
        window.localStorage.removeItem(`brand-os-regeneration-feedback:${selectedApproval.id}`);
        setReviewNote('');
        setStatusFilter('PENDING');
      }
      if (action === 'execute') setStatusFilter('EXECUTED');
      setOperationProgress(action === 'approve' || action === 'execute' ? 82 : 88);
      setOperationStage(action === 'regenerate' ? 'Refreshing the approval queue…' : 'Refreshing the workspace…');
      await fetchData();
      setOperationProgress(100);
      setOperationStage('Done');
      setNoticeTtl(action === 'regenerate' ? 1800 : 4500);
      setNotice(
        action === 'regenerate'
          ? 'Regenerated successfully.'
          : action === 'approve'
            ? 'Approved. The post is now locked and ready to execute.'
            : action === 'execute'
              ? 'Published to LinkedIn successfully.'
              : 'Action completed successfully.'
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approval action failed');
    } finally {
      setIsBusy(false);
      setBusyAction(null);
    }
  };

  const generateContent = async () => {
    if (!token) return;
    if (!requireBrand('generating content')) return;
    setIsGenerating(true); setError(null); setNoticeTtl(4500); setNotice(null);
    try {
      setGenerationProgress(34);
      setGenerationStage('Generating with AI…');
      const res = await fetch(API_BASE + '/api/agent/events', {
        method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: 'manual_generate_content', payload: { objective: 'Generate a fresh LinkedIn content opportunity for human review.' } }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Content generation failed'));
      setGenerationProgress(84);
      setGenerationStage('Refreshing the approval queue…');
      await fetchData();
      setGenerationProgress(100);
      setGenerationStage('Done');
      go('Dashboard');
      setNotice(
        data.approval_queued
          ? 'New content suggestion generated and added to the approval queue.'
          : data.blocked_by_guardrails
            ? 'Content was generated but held back by guardrails and was not added to the approval queue.'
            : data.duplicate_blocked
              ? 'The generated draft matched content already in your brand memory, so it was not added to the approval queue.'
              : 'No new suggestion was created. Try again with a different feedback or research angle.'
      );
    } catch (e) { setError(e instanceof Error ? e.message : 'Content generation failed'); }
    finally { setIsGenerating(false); }
  };

  const discoverResearch = async () => {
    if (!token) return;
    if (!requireBrand('running live research')) return;
    setIsResearching(true); setResearchProgress(8); setResearchStage('Starting live research…');
    setError(null); setNoticeTtl(4500); setNotice(null);
    try {
      const res = await fetch(API_BASE + '/api/research/discover', {
        method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: researchFocus.trim() || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Live research failed'));
      setResearchProgress(96);
      setResearchStage(data.fallback ? 'Using the latest available research evidence…' : 'Finalizing ranked opportunities…');
      setOpportunities(data.opportunities || []);
      setResearchProgress(100);
      setResearchStage('Research complete');
      setNotice(data.fallback
        ? 'Live sources were temporarily unavailable. Showing the latest available research evidence.'
        : 'Fresh research completed. Opportunities were ranked against your Brand DNA.');
    } catch (e) {
      setResearchProgress(0);
      setResearchStage('');
      setError(e instanceof Error ? e.message : 'Live research failed');
    } finally {
      setIsResearching(false);
    }
  };

  const updateHistoricalPost = (index: number, value: string) =>
    setHistoricalPostEntries((current) => current.map((post, i) => i === index ? value : post));
  const addHistoricalPost = () =>
    setHistoricalPostEntries((current) => current.length >= 10 ? current : [...current, '']);
  const removeHistoricalPost = (index: number) =>
    setHistoricalPostEntries((current) => current.filter((_, i) => i !== index));

  const buildBrand = async () => {
    if (!token) return;
    const blocks = historicalPostEntries.map((body) => body.trim()).filter(Boolean);
    const title = brandTitle.trim();
    const industry = brandIndustry.trim();
    const tone = brandTone.trim();
    const experience = typeof brandExperienceYears === 'number' ? brandExperienceYears : Number(brandExperienceYears);

    if (!title || !industry || !tone || !Number.isFinite(experience) || experience < 0) {
      setError('Professional title, industry, desired tone and years of experience are required.');
      return;
    }
    if (blocks.length < 3) {
      setError('Add at least 3 and up to 10 previous LinkedIn posts to build your Brand DNA.');
      return;
    }

    setIsBuildingBrand(true); setError(null); setNoticeTtl(4500); setNotice(null);
    try {
      const endpoint = '/api/brand/onboard';
      const body = {
        display_name: profile.display_name,
        professional_title: title,
        industry,
        tone,
        experience_years: experience,
        posts: blocks.map((body) => ({ body })),
      };

      const res = await fetch(API_BASE + endpoint, {
        method: 'POST',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Brand Intelligence setup failed'));

      const memory = data.brand_memory || {};
      setBrand({ ...memory, ready: memory.status === 'READY' });
      setNotice(
        'Brand Intelligence updated using your saved Brand DNA details and ' + blocks.length + ' imported posts.'
      );
      await fetchData();
      setBrandEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Brand Intelligence setup failed');
    } finally {
      setIsBuildingBrand(false);
    }
  };

  const improveDraft = async () => {
    if (!token || !draftBody.trim()) { setError('Write a draft first, then ask Brand OS to polish it.'); return; }
    if (!requireBrand('polishing content')) return;
    setIsImproving(true); setError(null); setNoticeTtl(4500); setNotice(null);
    try {
      const res = await fetch(API_BASE + '/api/content/improve', {
        method: 'POST',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: draftTitle, topic: draftTopic, body: draftBody, language: draftLanguage || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Content improvement failed'));
      setDraftTitle(data.title || draftTitle);
      setDraftTopic(data.topic || draftTopic);
      setDraftBody(data.body || draftBody);
      setImprovementNotes(data.changes || []);
      setNotice('Polished version ready for your preview. Nothing has been sent for approval yet.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Content improvement failed'); }
    finally { setIsImproving(false); }
  };

  const saveThought = async () => {
    if (!token || !draftBody.trim()) {
      setError('Write something first so Brand OS has a useful thought to learn from.');
      return;
    }
    if (!requireBrand('saving a personal thought')) return;
    setSavingThought(true); setError(null); setNotice(null);
    try {
      const res = await fetch(API_BASE + '/api/learning/thought', {
        method: 'POST',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draftBody, topic: draftTopic, title: draftTitle }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Could not save this thought'));
      setNotice('Saved as a personal thought. Brand OS will learn from it without treating it as a published opinion.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save this thought');
    } finally {
      setSavingThought(false);
    }
  };

  const createDraft = async () => {
    if (!token || !draftTitle.trim() || !draftTopic.trim() || !draftBody.trim()) {
      setError('Title, topic and draft body are required.'); return;
    }
    if (!requireBrand('sending content to approval')) return;
    setIsBusy(true); setError(null); setNoticeTtl(4500); setNotice(null);
    try {
      const res = await fetch(`${API_BASE}/api/content/drafts`, {
        method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: draftTitle, topic: draftTopic, pillar: 'Expertise', body: draftBody }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(getApiError(data, 'Draft creation failed'));
      setDraftTitle(''); setDraftTopic(''); setDraftBody('');
      await fetchData(); go('Dashboard');
      setNotice(data.approval_id ? 'Draft created and added to the HITL approval queue.' : 'Draft created but guardrails require edits.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Draft creation failed'); }
    finally { setIsBusy(false); }
  };

  if (!token) return <LoginScreen error={error} onConnect={connectLinkedIn} />;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Sparkles size={18} /></div>
          <div><div className="brand-name">Brand OS</div><div className="brand-sub">Personal Brand Manager</div></div>
        </div>
        <div className="nav-label">Workspace</div>
        {nav.map(([label, Icon, sub]) => (
          <button key={label} className={`nav-item ${tab === label ? 'active' : ''}`} onClick={() => go(label as Tab)}>
            <Icon size={16} /><span>{label}</span>{label === 'Dashboard' && summary.pending > 0 ? <em>{summary.pending}</em> : <ChevronRight size={13} opacity={.35} />}
          </button>
        ))}
        <div className="sidebar-spacer" />
        <div className="connection-card">
          <div className="connection-row">
            <span className={`connection-dot ${linkedin.connected ? 'live' : ''}`} />
            <span className="connection-title">{linkedin.connected ? 'LinkedIn connected' : 'LinkedIn not connected'}</span>
          </div>
          <div className="connection-meta">{linkedin.connected ? 'Official API connection is ready.' : 'Connect through official OAuth to enable publishing.'}</div>
          <button className="button ghost-dark" style={{ width: '100%', marginTop: 9 }} onClick={connectLinkedIn}>
            <Link2 size={13} /> {linkedin.connected ? 'Reconnect' : 'Connect'}
          </button>
        </div>
        <div className="connection-card">
          <div className="connection-row"><ShieldCheck size={15} color="#8b7cff" /><span className="connection-title">Human approval gate</span></div>
          <div className="connection-meta">No external LinkedIn action is executed without your explicit approval.</div>
        </div>
        <button className="side-button" onClick={logout}><LogOut size={14} /> Sign out <span style={{ marginLeft: 'auto' }}>⌘Q</span></button>
        <div className="brand-footer">Brand OS · by Kanishka</div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <div><div className="eyebrow">Workspace / {tab}</div><div className="topbar-title">{tab === 'Dashboard' ? 'Command center' : nav.find((x) => x[0] === tab)?.[2]}</div></div>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" title="Refresh workspace" onClick={() => fetchData()}><RefreshCw size={15} className={loading ? 'spin' : ''} /></button>
            <div className="avatar">{initials}</div>
          </div>
        </header>

        <main className="page">
          {notice && <div className="notice success"><CircleCheck size={15} /><span>{notice}</span></div>}
          {error && <div className="notice error"><X size={15} /><span>{error}</span></div>}

          {tab === 'Dashboard' && (
            <>
              <section className="hero" onClick={!brand.ready ? () => go('Brand DNA') : undefined} style={!brand.ready ? { cursor: 'pointer' } : undefined}>
                <div className="hero-grid">
                  <div>
                    <div className="page-kicker" style={{ color: '#bdb6ff' }}>
                      {brand.ready ? <><Sparkles size={13} /> Brand intelligence active</> : <><BrainCircuit size={13} /> Brand DNA setup required</>}
                    </div>
                    <h1>{brand.ready ? 'Turn your expertise into a recognizable point of view.' : 'Start by teaching Brand OS your voice.'}</h1>
                    <p>{brand.ready
                      ? 'Research, content strategy, drafting and review — orchestrated around your brand voice, with you always in control of what reaches LinkedIn.'
                      : 'Enter your professional title, industry, desired tone and years of experience. Then add 3–10 previous LinkedIn posts so Brand OS can learn your writing style.'}</p>
                    <div className="hero-actions">
                      <button
                        className="button primary progress-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (!brand.ready) {
                            go('Brand DNA');
                            return;
                          }
                          void generateContent();
                        }}
                        disabled={isGenerating}
                      >
                        <span className="button-content"><WandSparkles size={15} /> {isGenerating ? generationStage || 'Generating…' : brand.ready ? 'Generate content' : 'Build Brand DNA'}</span>
                        {isGenerating && <span className="button-progress-track"><span style={{ width: generationProgress + '%' }} /></span>}
                      </button>
                      <button className="button ghost-dark" onClick={(event) => { event.stopPropagation(); go('Research'); }}><Search size={15} /> Discover opportunities</button>
                    </div>
                  </div>
                  <div className="hero-status">
                    <div className="status-orb"><div className="orb-inner"><BrainCircuit size={30} /></div></div>
                    <div style={{ color: '#8f9ab1', fontSize: 10, textAlign: 'right' }}>AI prepared · human approved<br />No autonomous publishing</div>
                  </div>
                </div>
              </section>

              <div className="metrics">
                <Metric icon={Clock3} label="Awaiting approval" value={summary.pending} meta="Needs your decision" />
                <Metric icon={CircleCheck} label="Approved" value={summary.reviewed} meta="Approved for publication" />
                <Metric icon={TrendingUp} label="Published" value={summary.executed} meta="Tracked by Brand OS" />
                <Metric icon={ShieldCheck} label="Guardrail status" value="ON" meta="Claims · voice · duplicate · action" />
                <Metric icon={BrainCircuit} label="Brand Pulse" value={brand.ready ? 'ACTIVE' : 'INACTIVE'} meta={brand.ready ? ((brand.current_post_count ?? brand.source_post_count) + ' signals in memory') : 'Set up before AI actions'} />
              </div>

              <section className="panel approval-panel">
                <div className="panel-head">
                  <div><div className="panel-title">Approval queue</div><div className="panel-subtitle">Your editorial desk — review the exact content before anything external happens.</div></div>
                  <button className="button" onClick={() => go('Content')}><Plus size={14} /> New draft</button>
                </div>
                <ApprovalWorkspace
                  queue={filteredQueue} selected={selectedApproval} selectedId={selectedId}
                  setSelectedId={setSelectedId} searchTerm={searchTerm} setSearchTerm={setSearchTerm}
                  statusFilter={statusFilter} setStatusFilter={setStatusFilter}
                  dashboardCounts={dashboardCounts}
                  editedBody={editedBody} setEditedBody={setEditedBody}
                  reviewNote={reviewNote} setReviewNote={setReviewNote}
                  isBusy={isBusy} busyAction={busyAction} operationProgress={operationProgress} operationStage={operationStage}
                  onAction={runApprovalAction}
                />
              </section>
            </>
          )}

          {tab === 'Research' && <ResearchView opportunities={opportunities} researchFocus={researchFocus} setResearchFocus={setResearchFocus} isResearching={isResearching} researchProgress={researchProgress} researchStage={researchStage} onResearch={discoverResearch} />}
          {tab === 'Content' && <ContentStudio profile={profile} title={draftTitle} setTitle={setDraftTitle} topic={draftTopic} setTopic={setDraftTopic} body={draftBody} setBody={setDraftBody} language={draftLanguage} setLanguage={setDraftLanguage} busy={isBusy} improving={isImproving} improvementProgress={improvementProgress} improvementNotes={improvementNotes} onImprove={improveDraft} onSubmit={createDraft} savingThought={savingThought} onSaveThought={saveThought} learningStatus={learningStatus} />}
          {tab === 'LinkedIn Posts' && <LinkedInPostsView posts={queue.filter((item) => item.status === 'EXECUTED').slice(0, 10)} totalPublished={dashboardCounts.published} />}
          {tab === 'Analytics' && <AnalyticsView analytics={analytics} />}
          {tab === 'Brand DNA' && (
            <SettingsView
              brand={brand}
              profile={profile}
              brandTitle={brandTitle}
              setBrandTitle={setBrandTitle}
              brandIndustry={brandIndustry}
              setBrandIndustry={setBrandIndustry}
              brandExperienceYears={brandExperienceYears}
              setBrandExperienceYears={setBrandExperienceYears}
              brandTone={brandTone}
              setBrandTone={setBrandTone}
              posts={historicalPostEntries}
              updatePost={updateHistoricalPost}
              addPost={addHistoricalPost}
              removePost={removeHistoricalPost}
              building={isBuildingBrand}
              onBuild={buildBrand}
              linkedin={linkedin}
              onConnect={connectLinkedIn}
              editing={brandEditing}
              setEditing={setBrandEditing}
              onCancel={cancelBrandEdit}
            />
          )}
        </main>
      </div>

      <nav className="mobile-bottom-nav" aria-label="Mobile workspace navigation">
        {[
          ['Dashboard', LayoutDashboard, 'Home'],
          ['Research', Search, 'Research'],
          ['Content', FileText, 'Content'],
          ['LinkedIn Posts', ExternalLink, 'Posts'],
        ].map(([key, Icon, label]) => (
          <button key={key as string} className={`mobile-nav-item ${tab === key ? 'active' : ''}`} onClick={() => go(key as Tab)}>
            <Icon size={18} />
            <span>{label as string}</span>
          </button>
        ))}
        <button className={`mobile-nav-item ${moreOpen ? 'active' : ''}`} onClick={() => setMoreOpen((open) => !open)}>
          <MoreHorizontal size={19} />
          <span>More</span>
        </button>
      </nav>

      {moreOpen && (
        <>
          <div className="mobile-more-backdrop" onClick={closeMore} />
          <section className="mobile-more-sheet" aria-label="More workspace options">
            <div className="mobile-sheet-handle" />
            <div className="mobile-sheet-title">More</div>
            <div className="mobile-more-grid">
              <button onClick={() => go('Analytics')}><BarChart3 size={18} /><span>Analytics</span></button>
              <button onClick={() => go('Brand DNA')}><Settings size={18} /><span>Brand DNA</span></button>
              <button onClick={() => { closeMore(); connectLinkedIn(); }}><Link2 size={18} /><span>{linkedin.connected ? 'LinkedIn' : 'Connect LinkedIn'}</span></button>
              <button onClick={installBrandOS} disabled={isStandalone}><Download size={18} /><span>{isStandalone ? 'Installed' : 'Install Brand OS'}</span></button>
            </div>
            <div className="mobile-more-status">
              <span className={`connection-dot ${linkedin.connected ? 'live' : ''}`} />
              <div><strong>{linkedin.connected ? 'LinkedIn connected' : 'LinkedIn not connected'}</strong><span>{linkedin.connected ? 'Official API connection is ready.' : 'Connect through official OAuth to enable publishing.'}</span></div>
            </div>
            <button className="mobile-more-signout" onClick={logout}><LogOut size={17} /> Sign out</button>
            <div className="mobile-more-footer">Brand OS · by Kanishka</div>
          </section>
        </>
      )}

      {showIosInstallGuide && (
        <div className="install-guide-backdrop" onClick={() => setShowIosInstallGuide(false)}>
          <section className="install-guide" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Install Brand OS">
            <div className="install-guide-icon"><Download size={20} /></div>
            <h2>Add Brand OS to your iPhone</h2>
            <p>Safari can install Brand OS as an app on your Home Screen.</p>
            <ol>
              <li>Tap the <strong>Share</strong> button in Safari.</li>
              <li>Choose <strong>Add to Home Screen</strong>.</li>
              <li>Turn on <strong>Open as Web App</strong>, then tap <strong>Add</strong>.</li>
            </ol>
            <button className="button primary" onClick={() => setShowIosInstallGuide(false)}>Got it</button>
          </section>
        </div>
      )}
    </div>
  );
}

function LoginScreen({ error, onConnect }: { error: string | null; onConnect: () => void }) {
  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 22, background: 'radial-gradient(circle at 20% 10%, #e9e5ff, transparent 28%), radial-gradient(circle at 90% 80%, #dff9fb, transparent 30%), #f6f7fb' }}>
      <div className="login-shell">
        <div className="login-visual">
          <div className="brand-lockup" style={{ padding: 0 }}><div className="brand-mark"><Sparkles size={18}/></div><div><div className="brand-name">Brand OS</div><div className="brand-sub" style={{ color: '#7f8aa3' }}>Personal Brand Manager</div></div></div>
          <div style={{ position: 'relative', zIndex: 1, marginTop: 74 }}>
            <div className="page-kicker" style={{ color: '#bdb6ff' }}><Sparkles size={13}/> AI + human editorial control</div>
            <h1 style={{ fontFamily: 'Space Grotesk', fontSize: 47, lineHeight: 1.02, letterSpacing: '-.055em', margin: '12px 0 16px' }}>Your brand,<br/>with a brain.</h1>
            <p style={{ color: '#aeb7ca', maxWidth: 430, lineHeight: 1.65, fontSize: 13 }}>A professional operating system for discovering ideas, shaping your voice and preparing content — without giving an AI free rein over your identity.</p>
            <div style={{ display: 'grid', gap: 9, marginTop: 28 }}>
              {['Learns from approved content', 'Researches before drafting', 'Human approval before external actions'].map((x) => <div key={x} style={{ display: 'flex', gap: 9, alignItems: 'center', color: '#dce1ec', fontSize: 11 }}><CircleCheck size={15} color="#8b7cff"/>{x}</div>)}
            </div>
          </div>
        </div>
        <div className="login-form">
          <div className="page-kicker"><ShieldCheck size={13}/> Secure official connection</div>
          <h2 style={{ fontFamily: 'Space Grotesk', fontSize: 29, letterSpacing: '-.04em', margin: '10px 0 8px' }}>Connect LinkedIn</h2>
          <p style={{ color: '#667085', fontSize: 13, lineHeight: 1.6, margin: 0 }}>Brand OS uses LinkedIn's official OAuth flow. Your LinkedIn password is never entered into Brand OS.</p>
           <p style={{ color: '#667085', fontSize: 11, lineHeight: 1.55, margin: '10px 0 0' }}>You'll authenticate securely on LinkedIn. If you're already signed in, LinkedIn may take you straight in.</p>
          {error && <div className="notice error" style={{ marginTop: 16 }}><X size={15}/><span>{error}</span></div>}
          <button className="button primary" style={{ width: '100%', minHeight: 46, marginTop: 24 }} onClick={onConnect}><LinkedInMark size={18}/> Continue with LinkedIn</button>
          <div style={{ marginTop: 17, padding: 12, borderRadius: 12, background: '#f8f9fb', color: '#667085', fontSize: 10, lineHeight: 1.55 }}>OAuth permissions requested are limited to supported identity and posting capabilities. External actions remain behind the approval gate.</div>
        </div>
      </div>
    </main>
  );
}

function Metric({ icon: Icon, label, value, meta }: any) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={15}/></span></div><div className="metric-value">{value}</div><div className="metric-meta">{meta}</div></div>;
}

function MiniStat({ icon: Icon, label, value }: any) {
  return <div className="score-item"><div className="score-name" style={{ display: 'flex', gap: 5, alignItems: 'center' }}><Icon size={11}/>{label}</div><div className="score-value" style={{ fontSize: 11, lineHeight: 1.35 }}>{value}</div></div>;
}

// Production copy sync marker: ensure latest UI copy is included in deployment.
function ApprovalWorkspace(props: any) {
  const { queue, selected, selectedId, setSelectedId, searchTerm, setSearchTerm, statusFilter, setStatusFilter, dashboardCounts, editedBody, setEditedBody, reviewNote, setReviewNote, isBusy, busyAction, operationProgress, operationStage, onAction } = props;
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [mobileReviewOpen, setMobileReviewOpen] = useState(false);
  const [imagePreview, setImagePreview] = useState<string | null>(null);

  useEffect(() => {
    setSelectedImage(null);
    setImagePreview(null);
  }, [selectedId]);

  const chooseImage = (file: File | null) => {
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/gif'].includes(file.type)) {
      window.alert('Only JPEG or PNG images are supported.');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      window.alert('Image must be 4 MB or smaller.');
      return;
    }
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setSelectedImage(file);
    setImagePreview(URL.createObjectURL(file));
  };

  return (
    <div className="queue-layout">
      <div className="queue-list">
        <div className="queue-tools">
          <div className="searchbox"><Search size={13}/><input className="input" placeholder="Search drafts…" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} /></div>
          <div className="filter-row">
            {([
              ['PENDING', 'Pending'],
              ['NEEDS_REVIEW', 'Needs review'],
              ['REJECTED', 'Rejected'],
              ['EXECUTED', 'Published'],
            ] as const).map(([value, label]) => (
              <button key={value} className={`filter-chip ${statusFilter === value ? 'active' : ''}`} onClick={() => setStatusFilter(value)}>
  <span>{label}</span>
  <em className="filter-count">{value === 'PENDING' ? dashboardCounts.pending_filter : value === 'NEEDS_REVIEW' ? dashboardCounts.needs_review : value === 'REJECTED' ? dashboardCounts.rejected : dashboardCounts.published}</em>
</button>
            ))}
          </div>
        </div>
        <div className="queue-items">
          {queue.length ? queue.map((item: ApprovalItem) => (
            <button key={item.id} className={`queue-item ${selectedId === item.id ? 'selected' : ''}`} onClick={() => { setSelectedId(item.id); setMobileReviewOpen(true); }}>
              <div className="queue-item-top"><span className="queue-id">POST #{item.id}</span><StatusPill status={item.status}/></div>
              <div className="queue-action">{item.action_type}</div>
              <div className="queue-preview">{item.content.slice(0, 88)}{item.content.length > 88 ? '…' : ''}</div>
            </button>
          )) : <div className="empty-state"><div className="empty-icon"><FileText size={18}/></div><strong>Queue is clear</strong><span>Create a draft or generate content to start the review flow.</span></div>}
        </div>
      </div>
      <div className={`review-pane ${mobileReviewOpen ? 'mobile-review-open' : ''}`}>
        {selected ? (
          <>
            <button className="mobile-review-back" onClick={() => setMobileReviewOpen(false)}><ChevronRight size={16} style={{ transform: 'rotate(180deg)' }} /> Back to queue</button>
            <div className="review-head"><div><div className="review-label">Editorial review · post #{selected.id}</div><div className="review-title">{selected.action_type}</div></div><StatusPill status={selected.status}/></div>

            {['PENDING','EDITED','REGENERATED'].includes(selected.status) ? (
              <div className="review-editor">
                <div className="editor-toolbar"><span>Exact content bound to approval</span><span>{editedBody.length} chars</span></div>
                <textarea className="textarea" value={editedBody} onChange={(e) => setEditedBody(e.target.value)} />
                <div className="review-label" style={{ marginTop: 10, marginBottom: 7 }}>Feedback for regeneration <span className="form-help">(optional)</span></div>
                <textarea
                  className="textarea"
                  style={{ minHeight: 82, marginTop: 0 }}
                  value={reviewNote}
                  onChange={(e) => {
                    const value = e.target.value;
                    setReviewNote(value);
                    if (selected?.id) {
                      const key = `brand-os-regeneration-feedback:${selected.id}`;
                      if (value.trim()) window.localStorage.setItem(key, value);
                      else window.localStorage.removeItem(key);
                    }
                  }}
                  placeholder="Tell us what to change, add, or remove. Example: Make the opening less polished and add the point about stakeholder alignment."
                />
                <div className="review-actions">
                  <button className="button success progress-button" disabled={isBusy} onClick={() => onAction('approve')}>
                    <span className="button-content"><Check size={14}/> {busyAction === 'approve' ? operationStage || 'Approving…' : 'Approve'}</span>
                    {busyAction === 'approve' && <span className="button-progress-track"><span style={{ width: operationProgress + '%' }} /></span>}
                  </button>
                  <button className="button" disabled={isBusy} onClick={() => onAction('edit', { edited_body: editedBody, reason: reviewNote || 'Edited during review.' })}><Pencil size={14}/> Save edit</button>
                  <button className="button progress-button" disabled={isBusy || !reviewNote.trim()} title={!reviewNote.trim() ? 'Add feedback before regenerating.' : 'Regenerate using your feedback'} onClick={() => onAction('regenerate', { reason: reviewNote.trim() })}>
                    <span className="button-content"><RotateCcw size={14}/> {busyAction === 'regenerate' ? operationStage || 'Regenerating…' : 'Regenerate'}</span>
                    {busyAction === 'regenerate' && <span className="button-progress-track"><span style={{ width: operationProgress + '%' }} /></span>}
                  </button>
                  <button className="button danger" disabled={isBusy} onClick={() => onAction('reject', { reason: reviewNote || 'Rejected by reviewer.' })}><X size={14}/> Reject</button>
                </div>
                <div className="form-help" style={{ marginTop: 8 }}>{reviewNote.trim() ? 'Regenerate will use this feedback and keep the new version behind the approval gate.' : 'Add feedback above to enable Regenerate.'}</div>
              </div>
            ) : selected.status === 'APPROVED' ? (
              <div className="review-editor">
                <div className="notice success" style={{ marginTop: 0 }}><CircleCheck size={15}/><span>Approved and locked. The content can no longer be edited or regenerated.</span></div>
                <div className="editor-toolbar" style={{ marginTop: 12 }}><span>Locked approved content</span><span>{selected.content.length} chars</span></div>
                <div className="readonly-field" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.65, minHeight: 150 }}>{selected.content}</div>
                <div style={{ marginTop: 14, padding: 12, border: '1px dashed #d0d5dd', borderRadius: 12, background: '#fafafa' }}>
                  <div className="review-label" style={{ marginBottom: 7 }}>Optional photograph</div>
                  <div className="form-help" style={{ marginBottom: 9 }}>Add one JPEG or PNG image (up to 4 MB). The image is sent directly to LinkedIn during execution and is not stored by Brand OS.</div>
                  <input type="file" accept="image/jpeg,image/png" onChange={(e) => chooseImage(e.target.files?.[0] || null)} disabled={isBusy} />
                  {imagePreview && (
                    <div style={{ marginTop: 10 }}>
                      <img src={imagePreview} alt="Selected LinkedIn post image preview" style={{ display: 'block', width: '100%', maxHeight: 280, objectFit: 'contain', borderRadius: 10, background: '#f2f4f7' }} />
                      <button className="link-button" style={{ marginTop: 7 }} onClick={() => { if (imagePreview) URL.revokeObjectURL(imagePreview); setImagePreview(null); setSelectedImage(null); }}>Remove image</button>
                    </div>
                  )}
                </div>
                <div className="review-actions" style={{ marginTop: 14 }}>
                  <button className="button success progress-button" disabled={isBusy} onClick={() => onAction('execute', selectedImage)}>
                    <span className="button-content"><ExternalLink size={14}/> {busyAction === 'execute' ? operationStage || 'Publishing…' : 'Execute'}</span>
                    {busyAction === 'execute' && <span className="button-progress-track"><span style={{ width: operationProgress + '%' }} /></span>}
                  </button>
                </div>
              </div>
            ) : (
              <div className={selected.status === 'EXECUTED' ? 'notice success' : 'notice error'} style={{ marginTop: 0 }}>
                <CircleCheck size={15}/><span>{selected.status === 'EXECUTED' ? 'Approved and published to LinkedIn. This post is permanently locked.' : 'This post is no longer awaiting a decision.'}</span>
              </div>
            )}

            <div style={{ marginTop: 17 }}>
              <div className="review-label" style={{ marginBottom: 9 }}>Safety rail</div>
              <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>{['Claim guard','Voice guard','Duplicate guard','Action guard'].map((x) => <span key={x} className="tag"><ShieldCheck size={10}/>{x}</span>)}</div>
            </div>
          </>
        ) : <EmptyState icon={FileText} title="Select a draft" text="Your editorial workspace will appear here." />}
      </div>
    </div>
  );
}

function StatusPill({ status, label }: { status: string; label?: string }) {
  const cls = status.toLowerCase();
  return <span className={`status-pill ${cls}`}><span>●</span>{label || status}</span>;
}

function LinkedInPostsView({ posts, totalPublished }: { posts: ApprovalItem[]; totalPublished: number }) {
  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-kicker"><ExternalLink size={13}/> LinkedIn content</div>
          <h1 className="page-title">Your published LinkedIn posts.</h1>
          <p className="page-description">Your 10 most recently published LinkedIn posts are shown here. Older posts are retained as learning signals, not as a full content archive.</p>
        </div>
      </div>
      <section className="panel">
        <div className="panel-head">
          <div><div className="panel-title">Published posts</div><div className="panel-subtitle">{totalPublished > 10 ? `Showing the 10 most recent of ${totalPublished} published posts` : `Showing all ${totalPublished} published posts`}</div></div>
        </div>
        <div className="post-stack">
          {posts.length ? posts.map((post) => (
            <article className="post-entry" key={post.id}>
              <div className="post-entry-head">
                <span className="post-index">POST #{post.id}</span>
                <StatusPill status={post.status} label="Published"/>
              </div>
              {post.title ? <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 7 }}>{post.title}</div> : null}
              {post.topic ? <div className="form-help" style={{ marginBottom: 9 }}>{post.topic}</div> : null}
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.7, color: '#344054' }}>{post.content}</div>
              {post.approved_at ? <div className="form-help" style={{ marginTop: 10 }}>Approved {new Date(post.approved_at).toLocaleString()}</div> : null}
            </article>
          )) : <EmptyState icon={ExternalLink} title="No published posts yet" text="Once you publish a post through Brand OS, it will appear here automatically." />}
        </div>
      </section>
    </>
  );
}

function ResearchView({ opportunities, researchFocus, setResearchFocus, isResearching, researchProgress, researchStage, onResearch }: { opportunities: Opportunity[]; researchFocus: string; setResearchFocus: (value: string) => void; isResearching: boolean; researchProgress: number; researchStage: string; onResearch: () => void }) {
  const hasResearch = opportunities.length > 0;
  return (
    <>
      <div className="page-header">
        <div><div className="page-kicker"><Search size={13}/> Intelligence layer</div><h1 className="page-title">Research & opportunities</h1><p className="page-description">{hasResearch ? 'Your latest research is below. Add a focus whenever you want Brand OS to explore a specific topic.' : 'Live evidence is combined with your Brand DNA, recent research interests and learned context before an idea reaches the drafting engine.'}</p></div>
        <button className="button primary progress-button" onClick={onResearch} disabled={isResearching}>
          <span className="button-content"><Search size={14}/>{isResearching ? researchStage || 'Researching…' : hasResearch ? 'Research now' : 'Run research'}</span>
          {isResearching && <span className="button-progress-track"><span style={{ width: researchProgress + '%' }} /></span>}
        </button>
      </div>

      <section className="panel research-focus-panel">
        <div className="research-focus-copy">
          <div className="panel-title">Guide the research <span className="form-help">(optional)</span></div>
          <div className="panel-subtitle">Tell Brand OS what you want to explore. Leave it blank and Brand OS will use your Brand DNA plus what it has learned from your research and content.</div>
        </div>
        <div className="research-focus-row">
          <div className="research-focus-input">
            <Search size={15}/>
            <input
              className="input"
              value={researchFocus}
              onChange={(e) => setResearchFocus(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !isResearching) onResearch(); }}
              placeholder="e.g. AI adoption in consulting, stakeholder management, project governance"
              aria-label="Optional research focus"
            />
          </div>
          <button className="button primary" onClick={onResearch} disabled={isResearching}>
            <Search size={14}/>{isResearching ? 'Researching…' : hasResearch ? 'Research now' : 'Run research'}
          </button>
        </div>
      </section>

      <div className="research-grid">
        {opportunities.length ? opportunities.map((item) => <ResearchCard key={item.id} item={item}/>) :
          <section className="panel"><EmptyState icon={Search} title="No research yet" text="Add an optional focus above, or let Brand OS discover current topics from your Brand DNA." action="Run research" onAction={onResearch}/></section>}
      </div>
    </>
  );
}

function ResearchCard({ item }: { item: Opportunity }) {
  const brandRelevance = Number(item.scores?.brand_fit ?? 0);
  const evidenceStrength = Number(item.scores?.evidence_strength ?? 0);
  return (
    <article className="research-card">
      <div className="research-top">
        <div style={{ minWidth: 0 }}>
          <div className="tag-row"><span className="tag">{item.pillar}</span><span className="tag">{item.format || 'Insight post'}</span></div>
          <div className="research-title">{item.title}</div>
          <p className="research-angle">{item.angle}</p>
        </div>
      </div>

      <div className="research-relevance-grid">
        <div className="research-relevance-item">
          <div className="score-name">Relevant to your profile</div>
          <div className="research-relevance-value">{Math.round(brandRelevance)}%</div>
          <div className="score-bar"><span style={{ width: `${Math.min(100, Math.max(0, brandRelevance))}%` }}/></div>
        </div>
        <div className="research-relevance-item">
          <div className="score-name">Evidence quality</div>
          <div className="research-relevance-value">{Math.round(evidenceStrength)}%</div>
          <div className="score-bar"><span style={{ width: `${Math.min(100, Math.max(0, evidenceStrength))}%` }}/></div>
        </div>
      </div>

      {item.evidence?.summary && <div className="evidence-box"><b>What the source says:</b> {item.evidence.summary}</div>}
      {item.evidence?.why_now && <p className="research-why"><b>Why it matters now:</b> {item.evidence.why_now}</p>}
      {item.rationale && <p className="research-rationale">{item.rationale}</p>}
      {item.sources?.length ? (
        <div className="source-row">
          {item.sources.slice(0, 3).map((source, i) => source.url ? (
            <a className="source-link" key={i} href={source.url} target="_blank" rel="noreferrer">
              {source.domain || source.title || 'Read source'} <ExternalLink size={10}/>
            </a>
          ) : null)}
        </div>
      ) : null}
      {item.sources?.length ? (
        <div className="research-read-more">
          {item.sources.slice(0, 1).map((source, i) => source.url ? (
            <a className="button" key={i} href={source.url} target="_blank" rel="noreferrer">Read more <ArrowUpRight size={13}/></a>
          ) : null)}
        </div>
      ) : null}
    </article>
  );
}

function ContentStudio({ profile, title, setTitle, topic, setTopic, body, setBody, language, setLanguage, busy, improving, improvementProgress, improvementNotes, onImprove, onSubmit, savingThought, onSaveThought, learningStatus }: any) {
  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-kicker"><WandSparkles size={13}/> Editorial studio</div>
          <h1 className="page-title">Write it your way. Let Brand OS polish it.</h1>
          <p className="page-description">Start with your own idea and wording in any language. Brand OS can improve structure and clarity using your Brand DNA, then you preview the exact version before it enters the approval queue.</p>
          <div className="form-help" style={{ marginTop: 8 }}>Brand learning is active · {learningStatus?.memory_count ?? 0} learned signals · {learningStatus?.pending_events ?? 0} queued for processing</div>
        </div>
      </div>
      <section className="panel studio-grid">
        <div className="studio-form">
          <div className="form-group"><label className="form-label">Post heading / working title</label><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Write the idea or heading you have in mind" /></div>
          <div className="form-group"><label className="form-label">Topic / theme <span className="form-help">(optional)</span></label><input className="input" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What is this post about?" /></div>
          <div className="form-group"><label className="form-label">Your language</label><input className="input" value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="e.g. English, Hindi, Hinglish" /></div>
          <div className="form-group">
            <label className="form-label">Your draft</label>
            <textarea className="textarea" style={{ minHeight: 270 }} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write naturally. Do not worry about formatting — Brand OS will preserve your meaning and improve the presentation." />
          </div>
          <div style={{ display: 'flex', gap: 9, alignItems: 'center', flexWrap: 'wrap' }}>
            <button className="button primary progress-button" disabled={improving || !body.trim()} onClick={onImprove}>
              <span className="button-content"><WandSparkles size={14}/>{improving ? 'Polishing…' : 'Improvise / polish with Brand OS'}</span>
              {improving && <span className="button-progress-track"><span style={{ width: improvementProgress + '%' }} /></span>}
            </button>
            <button className="button dark" disabled={busy || !body.trim()} onClick={onSubmit}><ShieldCheck size={14}/>{busy ? 'Sending…' : 'Send this version to approval'}</button>
            <button className="button" disabled={savingThought || !body.trim()} onClick={onSaveThought}>{savingThought ? 'Saving…' : 'Save as personal thought'}</button>
          </div>
          {improvementNotes?.length ? <div style={{ marginTop: 12, padding: 11, borderRadius: 11, background: '#f8f7ff', color: '#667085', fontSize: 10, lineHeight: 1.5 }}><b style={{ color: '#5145cd' }}>What changed:</b> {improvementNotes.join(' · ')}</div> : null}
        </div>
        <div className="live-preview">
          <div className="panel-title" style={{ marginBottom: 4 }}>Preview before approval</div>
          <div className="panel-subtitle" style={{ marginBottom: 14 }}>This is the exact text you can send to the HITL queue. Nothing is published from this screen.</div>
          <div className="linkedin-card">
            <div className="li-head"><div className="li-avatar">{(profile.display_name || 'U').slice(0,1).toUpperCase()}</div><div><div className="li-name">{profile.display_name}</div><div className="li-meta">Professional profile · Draft</div></div></div>
            <div className="li-body">{body || 'Your polished post preview will appear here.'}</div>
            <div className="li-actions"><span>Like</span><span>Comment</span><span>Share</span></div>
          </div>
          <div style={{ marginTop: 12, padding: 11, borderRadius: 11, background: '#f8f7ff', color: '#667085', fontSize: 10, lineHeight: 1.5 }}><b style={{ color: '#5145cd' }}>HITL:</b> Polish → preview → send to approval → approve → publish. The AI never bypasses the approval gate.</div>
        </div>
      </section>
    </>
  );
}

function AnalyticsView({ analytics }: { analytics: any }) {
  const p = analytics?.pipeline || {};
  const live = analytics?.linkedin_performance || {};
  const totals = live.totals || {};
  const trend = Array.isArray(live.trend) ? live.trend : [];
  const cards = [
    ['Historical posts', p.historical_posts ?? 0, 'User-provided brand evidence'],
    ['Content created', p.content_items ?? 0, 'Drafts generated in Brand OS'],
    ['Awaiting approval', p.pending_approval ?? 0, 'Needs your decision'],
    ['Published', p.published_via_brand_os ?? 0, 'Published through approved workflow'],
  ];
  const maxImpressions = Math.max(1, ...trend.map((row: any) => Number(row.IMPRESSION || 0)));

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-kicker"><BarChart3 size={13}/> Performance intelligence</div>
          <h1 className="page-title">Know what the system is doing.</h1>
          <p className="page-description">Operational analytics are available now. LinkedIn performance uses official LinkedIn member analytics only when the required permissions are granted.</p>
        </div>
      </div>

      <div className="metrics">
        {cards.map(([label, value, meta]) => <Metric key={label as string} icon={BarChart3} label={label} value={value} meta={meta} />)}
      </div>

{/* Temporarily hidden until LinkedIn Community Management analytics access is available. Code intentionally retained. */}
      {false && (
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <div>
            <div className="panel-title">LinkedIn performance</div>
            <div className="panel-subtitle">
              {live.available ? `Official LinkedIn data · last ${live.window_days || 30} days` : 'Waiting for official LinkedIn analytics access'}
            </div>
          </div>
          <span className={`status-pill ${live.available ? 'approved' : 'edited'}`}>● {live.available ? 'CONNECTED' : 'NOT CONNECTED'}</span>
        </div>

        <div className="panel-body">
          {live.available ? (
            <>
              <div className="metrics" style={{ gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', marginBottom: 18 }}>
                <Metric icon={TrendingUp} label="Impressions" value={totals.IMPRESSION ?? 0} meta="Lifetime within selected window" />
                <Metric icon={Target} label="Reach" value={totals.MEMBERS_REACHED ?? 0} meta="Members reached" />
                <Metric icon={CircleCheck} label="Reactions" value={totals.REACTION ?? 0} meta="Total reactions" />
                <Metric icon={Activity} label="Comments" value={totals.COMMENT ?? 0} meta="Total comments" />
                <Metric icon={Zap} label="Engagement rate" value={`${live.engagement_rate ?? 0}%`} meta="Reactions + comments + reshares / impressions" />
              </div>

              <div className="panel" style={{ border: '1px solid #eaecf0', boxShadow: 'none' }}>
                <div className="panel-head">
                  <div><div className="panel-title">Daily trend</div><div className="panel-subtitle">Impressions and engagement reported by LinkedIn.</div></div>
                </div>
                <div className="panel-body">
                  {trend.length ? (
                    <div style={{ display: 'grid', gap: 9 }}>
                      {trend.slice(-14).map((row: any) => (
                        <div key={row.date} style={{ display: 'grid', gridTemplateColumns: '72px 1fr 70px', gap: 9, alignItems: 'center', fontSize: 10 }}>
                          <span style={{ color: '#667085' }}>{new Date(row.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                          <div style={{ height: 8, background: '#f2f4f7', borderRadius: 99, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.max(2, Math.round((Number(row.IMPRESSION || 0) / maxImpressions) * 100))}%`, height: '100%', background: '#5145cd', borderRadius: 99 }} />
                          </div>
                          <span style={{ textAlign: 'right', color: '#344054' }}>{Number(row.IMPRESSION || 0).toLocaleString()} imp.</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state" style={{ minHeight: 120 }}>
                      <strong>No daily activity returned yet</strong>
                      <span>LinkedIn may need more time to report analytics for newly published posts.</span>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state" style={{ minHeight: 210 }}>
              <div className="empty-icon"><TrendingUp size={19}/></div>
              <strong>Official LinkedIn performance data is not connected yet</strong>
              <span>{live.message || 'The app needs LinkedIn Community Management member analytics access before it can show impressions, reach and engagement.'}</span>
              {live.authorization_required ? (
                <div style={{ maxWidth: 620, fontSize: 10, lineHeight: 1.6, color: '#667085', marginTop: 6 }}>
                  Required permissions: <b>r_member_postAnalytics</b> for post performance and <b>r_member_profileAnalytics</b> for follower/profile trends. After those permissions are enabled for the LinkedIn developer app, reconnect the LinkedIn account so the new consent is issued.
                </div>
              ) : null}
            </div>
          )}
        </div>
      </section>
      )}

{/* Temporarily hidden until LinkedIn Community Management analytics access is available. Code intentionally retained. */}
      {false && (
      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head"><div><div className="panel-title">What will appear here</div><div className="panel-subtitle">Only observed LinkedIn data is used.</div></div></div>
        <div className="panel-body" style={{ color: '#667085', fontSize: 11, lineHeight: 1.7 }}>
          Once analytics access is active, this view will show post impressions, reach, reactions, comments, reshares and engagement trends from LinkedIn's official member analytics API. Brand OS will not scrape LinkedIn or fabricate performance numbers.
        </div>
      </section>
      )}
    </>
  );
}

function SettingsView(props: any) {
  const {
    brand, profile, brandTitle, setBrandTitle, brandIndustry, setBrandIndustry,
    brandExperienceYears, setBrandExperienceYears, brandTone, setBrandTone,
    posts, updatePost, addPost, removePost, building, onBuild, linkedin, onConnect,
    editing, setEditing, onCancel
  } = props;

  const count = posts.filter((x: string) => x.trim()).length;
  const experienceValue = brandExperienceYears === '' ? '' : String(brandExperienceYears);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-kicker"><BrainCircuit size={13}/> Brand intelligence</div>
          <h1 className="page-title">Your brand memory.</h1>
          <p className="page-description">Brand DNA is built from the details you provide and the writing evidence you explicitly import. LinkedIn is not used to auto-fill your Brand DNA.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={"status-pill " + (brand.ready ? 'approved' : 'edited')}>{brand.ready ? '● ACTIVE' : '● SETUP NEEDED'}</span>
          {brand.ready && !editing && <button className="button" onClick={() => setEditing(true)}><Pencil size={14}/> Manage Brand DNA</button>}
        </div>
      </div>

      {!brand.ready || editing ? (
        <div className="settings-stack">
          <section className="panel settings-card">
            <div className="panel-head" style={{ padding: 0, border: 0 }}>
              <div>
                <h2 className="settings-title">Build your Brand DNA</h2>
                <p className="settings-copy">Tell Brand OS the four profile facts you want it to use. Nothing here is auto-fetched from LinkedIn.</p>
              </div>
              {brand.ready && <button className="button" onClick={onCancel}><X size={14}/> Cancel</button>}
            </div>

            <div className="profile-grid" style={{ marginTop: 16 }}>
              <div className="form-group">
                <label className="form-label">Professional title</label>
                <input className="input" value={brandTitle} onChange={(e) => setBrandTitle(e.target.value)} placeholder="e.g. Product Leader, Founder, Engineering Manager" />
              </div>
              <div className="form-group">
                <label className="form-label">Industry</label>
                <input className="input" value={brandIndustry} onChange={(e) => setBrandIndustry(e.target.value)} placeholder="e.g. SaaS, FinTech, Healthcare, Consulting" />
              </div>
              <div className="form-group">
                <label className="form-label">Desired tone</label>
                <input className="input" value={brandTone} onChange={(e) => setBrandTone(e.target.value)} placeholder="e.g. Direct, practical and credible" />
              </div>
              <div className="form-group">
                <label className="form-label">Years of work experience</label>
                <input
                  className="input"
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={experienceValue}
                  onChange={(e) => {
                    const raw = e.target.value;
                    setBrandExperienceYears(raw === '' ? '' : Number(raw));
                  }}
                  placeholder="e.g. 8.5"
                />
                <span className="form-help">Decimal values are accepted.</span>
              </div>
            </div>

            <div style={{ marginTop: 14, padding: 11, borderRadius: 11, background: '#f8f7ff', color: '#667085', fontSize: 10, lineHeight: 1.55 }}>
              <b style={{ color: '#5145cd' }}>Your inputs:</b> These four details are passed directly into Brand Intelligence and future content generation. Brand OS will not replace them with LinkedIn profile data.
            </div>
          </section>

          <section className="panel settings-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <div>
                <h2 className="settings-title">Voice calibration</h2>
                <p className="settings-copy">Add 3–10 previous LinkedIn posts so Brand OS has enough evidence to learn your writing style.</p>
              </div>
              <span className={"status-pill " + (count >= 3 ? 'approved' : 'edited')}>{count}/10 posts</span>
            </div>

            <div className="post-stack">
              {posts.map((post: string, index: number) => (
                <div className="post-entry" key={index}>
                  <div className="post-entry-head">
                    <span className="post-index">SOURCE POST {String(index + 1).padStart(2,'0')}</span>
                    {posts.length > 1 && <button className="link-button" onClick={() => removePost(index)}>Remove</button>}
                  </div>
                  <textarea className="textarea" style={{ minHeight: 125 }} value={post} onChange={(e) => updatePost(index, e.target.value)} placeholder={'Paste the complete text of LinkedIn post ' + (index + 1) + '…'} />
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
              <button className="button" onClick={addPost} disabled={posts.length >= 10}><Plus size={14}/>{posts.length >= 10 ? 'Maximum reached' : 'Add another post'}</button>
              <button className="button primary" onClick={onBuild} disabled={building || count < 3}>
                <RefreshCw size={14}/>
                {building ? 'Building…' : brand.ready ? 'Refresh Brand Intelligence' : 'Build Brand DNA'}
              </button>
            </div>
            {count < 3 && (
              <div style={{ marginTop: 10, color: '#b42318', fontSize: 10 }}>
                Add {3 - count} more {3 - count === 1 ? 'post' : 'posts'} to build Brand DNA. You can provide up to 10.
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="settings-stack">
          <section className="panel settings-card">
            <div className="panel-head" style={{ padding: 0, border: 0 }}>
              <div><h2 className="settings-title">Saved Brand DNA</h2><p className="settings-copy">Read-only view of the profile context used by Brand OS.</p></div>
              <span className="tag"><ShieldCheck size={10}/> Frozen</span>
            </div>
            <div className="profile-grid" style={{ marginTop: 16 }}>
              {[
                ['Professional title', brandTitle],
                ['Industry', brandIndustry],
                ['Desired tone', brandTone],
                ['Years of work experience', experienceValue ? experienceValue + ' years' : ''],
              ].map(([label, value]) => (
                <div className="form-group" key={label as string}>
                  <span className="form-label">{label}</span>
                  <div className="readonly-field">{value || 'Not yet available'}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel settings-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14 }}>
              <div><h2 className="settings-title">Voice calibration</h2><p className="settings-copy">These imported posts are the source evidence used to calibrate your writing style. Brand OS can continue learning from approved and published content afterward.</p></div>
              <span className="status-pill approved">● {count} SAVED</span>
            </div>
            {count ? (
              <div className="post-stack" style={{ marginTop: 14 }}>
                {posts.filter((x: string) => x.trim()).map((post: string, index: number) => (
                  <div className="post-entry" key={index}>
                    <div className="post-entry-head"><span className="post-index">SOURCE POST {String(index + 1).padStart(2,'0')}</span></div>
                    <textarea className="textarea readonly-textarea" readOnly value={post} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state" style={{ minHeight: 120 }}>
                <strong>No historical posts imported</strong>
                <span>Import 3–10 previous LinkedIn posts to calibrate your writing style. Approved and published content can strengthen the model afterward.</span>
              </div>
            )}
          </section>

          <section className="panel settings-card">
            <h2 className="settings-title">Brand Intelligence status</h2>
            <p className="settings-copy">{brand.summary || 'Brand Intelligence is active and ready to shape content.'}</p>
            <div className="learning-flow">
              <div className="flow-step"><BrainCircuit size={15} color="#6d5dfc"/><b>Professional title</b><span>{brand.profile?.professional_title || 'Not set'}</span></div>
              <div className="flow-step"><Target size={15} color="#6d5dfc"/><b>Industry</b><span>{brand.profile?.industry || 'Not set'}</span></div>
              <div className="flow-step"><Sparkles size={15} color="#6d5dfc"/><b>Voice</b><span>{brand.profile?.tone || 'Not set'}</span></div>
              <div className="flow-step"><Activity size={15} color="#6d5dfc"/><b>Experience</b><span>{brand.profile?.experience_years != null ? brand.profile.experience_years + ' years' : 'Not set'} · {brand.current_post_count ?? brand.source_post_count} signals</span></div>
            </div>
          </section>
        </div>
      )}

      <section className="panel settings-card" style={{ marginTop: 16 }}>
        <h2 className="settings-title">LinkedIn connection</h2>
        <p className="settings-copy">Signed in as <b>{profile.display_name}</b>. {linkedin.connected ? 'Your official LinkedIn connection is active for supported publishing actions. It does not auto-fill your Brand DNA.' : 'Connect LinkedIn to enable supported publishing actions.'}</p>
        <button className="button" onClick={onConnect}><Link2 size={14}/>{linkedin.connected ? 'Reconnect LinkedIn' : 'Connect LinkedIn'}</button>
      </section>
    </>
  );
}

function EmptyState({ icon: Icon, title, text, action, onAction }: any) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={19}/></div><strong>{title}</strong><span>{text}</span>{action && <div style={{ marginTop: 14 }}><button className="button primary" onClick={onAction}>{action}<ChevronRight size={13}/></button></div>}</div>;
}

function LinkedInMark({ size = 18, color }: { size?: number; color?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill={color || 'currentColor'} aria-hidden="true"><path d="M6.5 8.2H3.2V20h3.3V8.2ZM4.85 3A1.95 1.95 0 1 0 4.85 6.9 1.95 1.95 0 0 0 4.85 3ZM20.8 13.25c0-3.52-1.88-5.16-4.4-5.16-2.02 0-2.92 1.11-3.43 1.89V8.2H9.67V20h3.3v-5.84c0-1.54.29-3.03 2.2-3.03 1.88 0 1.91 1.76 1.91 3.13V20h3.3l.02-6.75Z"/></svg>;
}
