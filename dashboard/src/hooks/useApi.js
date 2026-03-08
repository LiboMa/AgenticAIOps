import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000`

const fetcher = async (path) => {
  const res = await fetch(`${API_URL}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

const poster = async (path, body) => {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

const patcher = async (path, body) => {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ── Ops Hub ──
export const useHealthIssues = () =>
  useQuery({ queryKey: ['health-issues'], queryFn: () => fetcher('/api/health-issues'), refetchInterval: 30_000 })

export const useHealthIssueDetail = (id) =>
  useQuery({ queryKey: ['health-issue', id], queryFn: () => fetcher(`/api/health-issues/${id}`), enabled: !!id })

export const useUpdateHealthIssueStatus = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, note }) => patcher(`/api/health-issues/${id}/status`, { status, note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['health-issues'] }),
  })
}

export const useAlertFeed = (limit = 50) =>
  useQuery({ queryKey: ['alert-feed', limit], queryFn: () => fetcher(`/api/alert/feed?limit=${limit}`), refetchInterval: 10_000 })

export const useAlertStats = () =>
  useQuery({ queryKey: ['alert-stats'], queryFn: () => fetcher('/api/alert/stats'), refetchInterval: 30_000 })

export const useIncidentStats = () =>
  useQuery({ queryKey: ['incident-stats'], queryFn: () => fetcher('/api/incident/stats'), refetchInterval: 60_000 })

export const useIncidentList = () =>
  useQuery({ queryKey: ['incidents'], queryFn: () => fetcher('/api/incident/list'), refetchInterval: 30_000 })

// ── Diagnose ──
export const useRCAReports = () =>
  useQuery({ queryKey: ['rca-reports'], queryFn: () => fetcher('/api/rca/reports'), refetchInterval: 60_000 })

export const useRCADetail = (id) =>
  useQuery({ queryKey: ['rca-report', id], queryFn: () => fetcher(`/api/rca/reports/${id}`), enabled: !!id })

export const useTriggerRCA = () =>
  useMutation({ mutationFn: (body) => poster('/api/rca/analyze', body) })

export const useKnowledgeSearch = () =>
  useMutation({ mutationFn: (query) => poster('/api/knowledge/search', { query }) })

export const useKnowledgePatterns = () =>
  useQuery({ queryKey: ['knowledge-patterns'], queryFn: () => fetcher('/api/knowledge/patterns'), refetchInterval: 120_000 })

export const useTopology = (vpcId) =>
  useQuery({ queryKey: ['topology', vpcId], queryFn: () => fetcher(`/api/topology/vpc/${vpcId}`), enabled: !!vpcId })

export const useTopologyPropagation = (vpcId) =>
  useQuery({ queryKey: ['topology-propagation', vpcId], queryFn: () => fetcher(`/api/topology/vpc/${vpcId}/propagation`), enabled: !!vpcId })

export const useTopologyChanges = (vpcId) =>
  useQuery({ queryKey: ['topology-changes', vpcId], queryFn: () => fetcher(`/api/topology/vpc/${vpcId}/changes`), enabled: !!vpcId })

// ── SOP ──
export const useSOPList = () =>
  useQuery({ queryKey: ['sop-list'], queryFn: () => fetcher('/api/sop/list'), refetchInterval: 60_000 })

export const useSOPDetail = (id) =>
  useQuery({ queryKey: ['sop', id], queryFn: () => fetcher(`/api/sop/${id}`), enabled: !!id })

export const useExecuteSOP = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => poster('/api/sop/execute', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sop-list'] }),
  })
}

// ── Safety / Approvals ──
export const useSafetyApprovals = () =>
  useQuery({ queryKey: ['safety-approvals'], queryFn: () => fetcher('/api/safety/approvals'), refetchInterval: 10_000 })

export const useApproveAction = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => poster(`/api/safety/approve/${id}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['safety-approvals'] }),
  })
}

export const useRejectAction = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => poster(`/api/safety/reject/${id}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['safety-approvals'] }),
  })
}

// ── Agent / Detect ──
export const useDetectStatus = () =>
  useQuery({ queryKey: ['detect-status'], queryFn: () => fetcher('/api/detect/status'), refetchInterval: 30_000 })

// ── Config ──
export const useProactiveStatus = () =>
  useQuery({ queryKey: ['proactive-status'], queryFn: () => fetcher('/api/proactive/status'), refetchInterval: 60_000 })

export const useRegistryStatus = () =>
  useQuery({ queryKey: ['registry-status'], queryFn: () => fetcher('/api/registry/status'), refetchInterval: 120_000 })

export const useRunbooks = () =>
  useQuery({ queryKey: ['runbooks'], queryFn: () => fetcher('/api/runbooks'), refetchInterval: 120_000 })
