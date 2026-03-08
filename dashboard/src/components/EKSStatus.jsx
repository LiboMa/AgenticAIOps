import { useState, useEffect } from 'react'
import {
  Box, Paper, Grid, Typography, Chip, Table, TableBody, 
  TableCell, TableHead, TableRow, Card, CardContent, 
  LinearProgress, IconButton, Tooltip
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import WarningIcon from '@mui/icons-material/Warning'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function EKSStatus() {
  const [loading, setLoading] = useState(true)
  const [clusterInfo, setClusterInfo] = useState(null)
  const [pods, setPods] = useState([])
  const [nodes, setNodes] = useState([])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [clusterRes, podsRes, nodesRes] = await Promise.all([
        axios.get(`${API_URL}/api/cluster/info`),
        axios.get(`${API_URL}/api/pods`),
        axios.get(`${API_URL}/api/nodes`)
      ])
      setClusterInfo(clusterRes.data)
      setPods(podsRes.data.pods || [])
      setNodes(nodesRes.data.nodes || [])
    } catch (error) {
      console.error('Error fetching data:', error)
      // Use mock data for demo
      setClusterInfo({
        name: 'testing-cluster',
        version: '1.32',
        status: 'ACTIVE',
        region: 'ap-southeast-1'
      })
      setPods([
        { name: 'shop-frontend-abc', namespace: 'onlineshop', status: 'Running', restarts: 0 },
        { name: 'shop-api-def', namespace: 'onlineshop', status: 'Running', restarts: 0 },
        { name: 'crashloop-app-xyz', namespace: 'faulty-apps', status: 'CrashLoopBackOff', restarts: 15 },
        { name: 'oom-app-123', namespace: 'faulty-apps', status: 'OOMKilled', restarts: 8 },
      ])
      setNodes([
        { name: 'ip-10-0-1-100', status: 'Ready', cpu: '45%', memory: '62%' },
        { name: 'ip-10-0-2-101', status: 'Ready', cpu: '38%', memory: '55%' },
      ])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const getStatusIcon = (status) => {
    if (status === 'Running' || status === 'Ready' || status === 'ACTIVE') {
      return <CheckCircleIcon sx={{ color: '#3fb950' }} />
    } else if (status?.includes('Error') || status?.includes('OOM') || status?.includes('Crash')) {
      return <ErrorIcon sx={{ color: '#f85149' }} />
    }
    return <WarningIcon sx={{ color: '#d29922' }} />
  }

  const getStatusColor = (status) => {
    if (status === 'Running' || status === 'Ready' || status === 'ACTIVE') return 'success'
    if (status?.includes('Error') || status?.includes('OOM') || status?.includes('Crash')) return 'error'
    return 'warning'
  }

  return (
    <Box>
      {loading && <LinearProgress sx={{ mb: 2 }} />}
      
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">EKS Cluster Status</Typography>
        <Tooltip title="Refresh">
          <IconButton onClick={fetchData} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Cluster Info Cards */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={3}>
          <Card sx={{ backgroundColor: '#21262d' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Cluster</Typography>
              <Typography variant="h6">{clusterInfo?.name || '-'}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ backgroundColor: '#21262d' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Version</Typography>
              <Typography variant="h6">{clusterInfo?.version || '-'}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ backgroundColor: '#21262d' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Status</Typography>
              <Chip 
                label={clusterInfo?.status || '-'} 
                color={getStatusColor(clusterInfo?.status)}
                size="small"
              />
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ backgroundColor: '#21262d' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>Nodes</Typography>
              <Typography variant="h6">{nodes.length}</Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Nodes Table */}
      <Typography variant="h6" sx={{ mb: 1 }}>Nodes</Typography>
      <Paper sx={{ mb: 3, backgroundColor: '#21262d' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>CPU</TableCell>
              <TableCell>Memory</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {nodes.map((node, i) => (
              <TableRow key={i}>
                <TableCell>{node.name}</TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    {getStatusIcon(node.status)}
                    {node.status}
                  </Box>
                </TableCell>
                <TableCell>{node.cpu}</TableCell>
                <TableCell>{node.memory}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      {/* Pods Table */}
      <Typography variant="h6" sx={{ mb: 1 }}>Pods ({pods.length})</Typography>
      <Paper sx={{ backgroundColor: '#21262d' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Namespace</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Restarts</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {pods.map((pod, i) => (
              <TableRow key={i}>
                <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                  {pod.name}
                </TableCell>
                <TableCell>{pod.namespace}</TableCell>
                <TableCell>
                  <Chip 
                    label={pod.status} 
                    color={getStatusColor(pod.status)}
                    size="small"
                    icon={getStatusIcon(pod.status)}
                  />
                </TableCell>
                <TableCell>
                  <Typography color={pod.restarts > 5 ? 'error' : 'inherit'}>
                    {pod.restarts}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  )
}

export default EKSStatus
