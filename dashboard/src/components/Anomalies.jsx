import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Alert, AlertTitle, Chip, 
  List, ListItem, ListItemIcon, ListItemText, IconButton,
  Tooltip, Collapse, Button
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import ErrorIcon from '@mui/icons-material/Error'
import WarningIcon from '@mui/icons-material/Warning'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function Anomalies() {
  const [anomalies, setAnomalies] = useState([])
  const [expanded, setExpanded] = useState({})
  const [loading, setLoading] = useState(false)

  const fetchAnomalies = async () => {
    setLoading(true)
    try {
      const response = await axios.get(`${API_URL}/api/anomalies`)
      setAnomalies(response.data.anomalies || [])
    } catch (error) {
      // Mock data for demo
      setAnomalies([
        {
          id: 1,
          severity: 'critical',
          type: 'CrashLoopBackOff',
          resource: 'crashloop-app',
          namespace: 'faulty-apps',
          message: 'Pod has restarted 15 times in the last hour',
          timestamp: new Date().toISOString(),
          aiSuggestion: 'Check application logs with `kubectl logs crashloop-app --previous`. The pod is likely crashing due to application error or missing configuration. Review the container entrypoint and environment variables.'
        },
        {
          id: 2,
          severity: 'critical',
          type: 'OOMKilled',
          resource: 'oom-app',
          namespace: 'faulty-apps',
          message: 'Container killed due to out of memory',
          timestamp: new Date().toISOString(),
          aiSuggestion: 'Increase memory limits in deployment spec. Current limit appears too low for application requirements. Consider setting limits to at least 512Mi for this workload.'
        },
        {
          id: 3,
          severity: 'warning',
          type: 'ImagePullBackOff',
          resource: 'imagepull-app',
          namespace: 'faulty-apps',
          message: 'Failed to pull image: non-existent-image:latest',
          timestamp: new Date().toISOString(),
          aiSuggestion: 'Verify image name and tag exist in the registry. Check if imagePullSecrets are configured correctly for private registries.'
        },
        {
          id: 4,
          severity: 'warning',
          type: 'HighRestarts',
          resource: 'shop-worker',
          namespace: 'onlineshop',
          message: 'Pod restart count exceeds threshold (>5 in 1h)',
          timestamp: new Date().toISOString(),
          aiSuggestion: 'Monitor application health. Check liveness/readiness probe configurations. Review recent deployments for changes that may have introduced instability.'
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAnomalies()
  }, [])

  const toggleExpand = (id) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical': return 'error'
      case 'warning': return 'warning'
      case 'info': return 'info'
      default: return 'default'
    }
  }

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'critical': return <ErrorIcon color="error" />
      case 'warning': return <WarningIcon color="warning" />
      default: return <WarningIcon />
    }
  }

  const criticalCount = anomalies.filter(a => a.severity === 'critical').length
  const warningCount = anomalies.filter(a => a.severity === 'warning').length

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Box>
          <Typography variant="h5">Anomaly Detection</Typography>
          <Box sx={{ mt: 1, display: 'flex', gap: 1 }}>
            <Chip 
              label={`${criticalCount} Critical`} 
              color="error" 
              size="small" 
              icon={<ErrorIcon />}
            />
            <Chip 
              label={`${warningCount} Warning`} 
              color="warning" 
              size="small"
              icon={<WarningIcon />}
            />
          </Box>
        </Box>
        <Tooltip title="Refresh">
          <IconButton onClick={fetchAnomalies} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      <List>
        {anomalies.map((anomaly) => (
          <Paper key={anomaly.id} sx={{ mb: 2, backgroundColor: '#21262d' }}>
            <ListItem 
              secondaryAction={
                <IconButton onClick={() => toggleExpand(anomaly.id)}>
                  {expanded[anomaly.id] ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                </IconButton>
              }
            >
              <ListItemIcon>
                {getSeverityIcon(anomaly.severity)}
              </ListItemIcon>
              <ListItemText
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Chip 
                      label={anomaly.type} 
                      color={getSeverityColor(anomaly.severity)} 
                      size="small" 
                    />
                    <Typography variant="body1" sx={{ fontFamily: 'monospace' }}>
                      {anomaly.namespace}/{anomaly.resource}
                    </Typography>
                  </Box>
                }
                secondary={
                  <Typography variant="body2" color="text.secondary">
                    {anomaly.message}
                  </Typography>
                }
              />
            </ListItem>
            
            <Collapse in={expanded[anomaly.id]}>
              <Box sx={{ p: 2, pt: 0 }}>
                <Alert 
                  severity="info" 
                  icon={<SmartToyIcon />}
                  sx={{ backgroundColor: '#1a2332' }}
                >
                  <AlertTitle>AI Recommendation</AlertTitle>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                    {anomaly.aiSuggestion}
                  </Typography>
                </Alert>
                <Box sx={{ mt: 1, display: 'flex', gap: 1 }}>
                  <Button size="small" variant="outlined" color="primary">
                    View Logs
                  </Button>
                  <Button size="small" variant="outlined" color="primary">
                    Start RCA
                  </Button>
                </Box>
              </Box>
            </Collapse>
          </Paper>
        ))}
      </List>

      {anomalies.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center', backgroundColor: '#21262d' }}>
          <Typography color="text.secondary">
            No anomalies detected. Your cluster is healthy! 🎉
          </Typography>
        </Paper>
      )}
    </Box>
  )
}

export default Anomalies
