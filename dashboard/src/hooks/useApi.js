import { useQuery } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000`

const fetcher = async (path) => {
  const res = await fetch(`${API_URL}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const useHealthIssues = () =>
  useQuery({
    queryKey: ['health-issues'],
    queryFn: () => fetcher('/api/health-issues'),
    refetchInterval: 30_000,
  })

export const useAlertFeed = (limit = 50) =>
  useQuery({
    queryKey: ['alert-feed', limit],
    queryFn: () => fetcher(`/api/alert/feed?limit=${limit}`),
    refetchInterval: 10_000,
  })

export const useAlertStats = () =>
  useQuery({
    queryKey: ['alert-stats'],
    queryFn: () => fetcher('/api/alert/stats'),
    refetchInterval: 30_000,
  })

export const useIncidentStats = () =>
  useQuery({
    queryKey: ['incident-stats'],
    queryFn: () => fetcher('/api/incident/stats'),
    refetchInterval: 60_000,
  })

export const useRCAReports = () =>
  useQuery({
    queryKey: ['rca-reports'],
    queryFn: () => fetcher('/api/rca/reports'),
    refetchInterval: 60_000,
  })

export const useSOPList = () =>
  useQuery({
    queryKey: ['sop-list'],
    queryFn: () => fetcher('/api/sop/list'),
    refetchInterval: 60_000,
  })

export const useTopology = (vpcId) =>
  useQuery({
    queryKey: ['topology', vpcId],
    queryFn: () => fetcher(`/api/topology/vpc/${vpcId}`),
    enabled: !!vpcId,
  })

export const useProactiveStatus = () =>
  useQuery({
    queryKey: ['proactive-status'],
    queryFn: () => fetcher('/api/proactive/status'),
    refetchInterval: 60_000,
  })
