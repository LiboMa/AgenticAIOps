import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Grid, Typography, Chip, Table, TableBody, 
  TableCell, TableHead, TableRow, Card, CardContent, 
  LinearProgress, IconButton, Tooltip, TextField, Button,
  Alert, Tabs, Tab, CircularProgress, Accordion, AccordionSummary,
  AccordionDetails, List, ListItem, ListItemText, Divider
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import WarningIcon from '@mui/icons-material/Warning'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function ACITelemetry({ activeCluster }) {
  const [loading, setLoading] = useState(false)
  const [namespace, setNamespace] = useState('stress-test')
  const [activeTab, setActiveTab] = useState(0)
  const [aciStatus, setAciStatus] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [diagnosis, setDiagnosis] = useState(null)
  const [diagnosisLoading, setDiagnosisLoading] = useState(false)
  const [error, setError] = useState(null)

  // Check ACI status on mount
  useEffect(() => {
    checkAciStatus()
  }, [])

  const checkAciStatus = async () => {
    try {
      const res = await axios.get(`${API_URL}/api/aci/status`)
      setAciStatus(res.data)
    } catch (e) {
      setAciStatus({ aci_available: false, voting_available: false })
    }
  }

  const fetchTelemetry = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`${API_URL}/api/aci/telemetry/${namespace}`)
      if (res.data.error) {
        setError(res.data.error)
      } else {
        setTelemetry(res.data)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const runDiagnosis = async () => {
    setDiagnosisLoading(true)
    setError(null)
    try {
      const res = await axios.post(`${API_URL}/api/aci/diagnosis`, {
        namespace: namespace,
        query: "What is wrong with this namespace?"
      })
      if (res.data.error) {
        setError(res.data.error)
      } else {
        setDiagnosis(res.data.report)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setDiagnosisLoading(false)
    }
  }

  const getSeverityIcon = (severity) => {
    switch (severity?.toLowerCase()) {
      case 'error':
      case 'critical':
        return <ErrorIcon sx={{ color: '#f85149', fontSize: 16 }} />
      case 'warning':
        return <WarningIcon sx={{ color: '#d29922', fontSize: 16 }} />
      default:
        return <CheckCircleIcon sx={{ color: '#3fb950', fontSize: 16 }} />
    }
  }

  const getEventColor = (type) => {
    return type === 'Warning' ? 'warning' : type === 'Normal' ? 'success' : 'default'
  }

  return (
    <Box>
      {/* ACI Status Banner */}
      <Box sx={{ mb: 2 }}>
        {aciStatus ? (
          <Alert 
            severity={aciStatus.aci_available ? "success" : "warning"}
            sx={{ backgroundColor: aciStatus.aci_available ? '#1a3d1a' : '#3d3a1a' }}
          >
            <Box sx={{ display: 'flex', gap: 3 }}>
              <span>
                <strong>ACI:</strong> {aciStatus.aci_available ? '✅ Connected' : '❌ Not Available'}
              </span>
              <span>
                <strong>Voting:</strong> {aciStatus.voting_available ? '✅ Ready' : '❌ Not Available'}
              </span>
            </Box>
          </Alert>
        ) : (
          <LinearProgress />
        )}
      </Box>

      {/* Controls */}
      <Paper sx={{ p: 2, mb: 2, backgroundColor: '#21262d' }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <TextField
            label="Namespace"
            value={namespace}
            onChange={(e) => setNamespace(e.target.value)}
            size="small"
            sx={{ width: 200 }}
          />
          <Button
            variant="contained"
            onClick={fetchTelemetry}
            disabled={loading || !aciStatus?.aci_available}
            startIcon={loading ? <CircularProgress size={16} /> : <RefreshIcon />}
          >
            Fetch Telemetry
          </Button>
          <Button
            variant="outlined"
            color="secondary"
            onClick={runDiagnosis}
            disabled={diagnosisLoading || !aciStatus?.voting_available}
            startIcon={diagnosisLoading ? <CircularProgress size={16} /> : <PlayArrowIcon />}
            sx={{ ml: 'auto' }}
          >
            Run Diagnosis
          </Button>
        </Box>
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
      )}

      {/* Telemetry Data Tabs */}
      {telemetry && (
        <Paper sx={{ backgroundColor: '#21262d' }}>
          <Tabs
            value={activeTab}
            onChange={(e, v) => setActiveTab(v)}
            sx={{ borderBottom: 1, borderColor: 'divider' }}
          >
            <Tab label={`📋 Events (${telemetry.events?.data?.length || 0})`} />
            <Tab label={`📊 Metrics`} />
            <Tab label={`📝 Logs (${telemetry.logs?.data?.length || 0})`} />
          </Tabs>

          <Box sx={{ p: 2 }}>
            {/* Events Tab */}
            {activeTab === 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1, color: '#8b949e' }}>
                  K8s Events from namespace: <strong>{namespace}</strong>
                </Typography>
                {telemetry.events?.data?.length > 0 ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Type</TableCell>
                        <TableCell>Reason</TableCell>
                        <TableCell>Object</TableCell>
                        <TableCell>Message</TableCell>
                        <TableCell>Time</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {telemetry.events.data.map((event, i) => (
                        <TableRow key={i}>
                          <TableCell>
                            <Chip 
                              label={event.event_type} 
                              size="small" 
                              color={getEventColor(event.event_type)}
                            />
                          </TableCell>
                          <TableCell>{event.reason}</TableCell>
                          <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                            {event.object}
                          </TableCell>
                          <TableCell sx={{ maxWidth: 400 }}>{event.message}</TableCell>
                          <TableCell sx={{ whiteSpace: 'nowrap' }}>
                            {new Date(event.timestamp).toLocaleTimeString()}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Typography color="text.secondary">No events found</Typography>
                )}
              </Box>
            )}

            {/* Metrics Tab */}
            {activeTab === 1 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 2, color: '#8b949e' }}>
                  Metrics from Prometheus/CloudWatch
                </Typography>
                <Grid container spacing={2}>
                  {Object.entries(telemetry.metrics?.data || {}).map(([name, value]) => (
                    <Grid item xs={12} md={4} key={name}>
                      <Card sx={{ backgroundColor: '#161b22' }}>
                        <CardContent>
                          <Typography color="text.secondary" variant="body2">
                            {name.replace(/_/g, ' ').toUpperCase()}
                          </Typography>
                          <Typography variant="h5" sx={{ mt: 1 }}>
                            {typeof value === 'number' ? value.toFixed(2) : value || 'N/A'}
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                  {Object.keys(telemetry.metrics?.data || {}).length === 0 && (
                    <Grid item xs={12}>
                      <Typography color="text.secondary">No metrics available</Typography>
                    </Grid>
                  )}
                </Grid>
              </Box>
            )}

            {/* Logs Tab */}
            {activeTab === 2 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1, color: '#8b949e' }}>
                  Error Logs (last 30 min)
                </Typography>
                {telemetry.logs?.data?.length > 0 ? (
                  <Paper sx={{ backgroundColor: '#0d1117', p: 2, maxHeight: 400, overflow: 'auto' }}>
                    {telemetry.logs.data.map((log, i) => (
                      <Box key={i} sx={{ mb: 1, fontFamily: 'monospace', fontSize: '0.85rem' }}>
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          {getSeverityIcon(log.severity)}
                          <Typography variant="caption" color="text.secondary">
                            [{log.timestamp}] {log.pod_name}
                          </Typography>
                        </Box>
                        <Typography sx={{ ml: 3, color: '#c9d1d9' }}>
                          {log.message}
                        </Typography>
                      </Box>
                    ))}
                  </Paper>
                ) : (
                  <Typography color="text.secondary">No error logs found</Typography>
                )}
              </Box>
            )}
          </Box>
        </Paper>
      )}

      {/* Diagnosis Result */}
      {diagnosis && (
        <Paper sx={{ mt: 2, backgroundColor: '#21262d' }}>
          <Box sx={{ p: 2 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              🔍 Multi-Agent Diagnosis Result
            </Typography>
            
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Card sx={{ backgroundColor: '#161b22' }}>
                  <CardContent>
                    <Typography color="text.secondary" gutterBottom>Final Diagnosis</Typography>
                    <Typography variant="h6" color="primary">
                      {diagnosis.final_diagnosis || 'No diagnosis'}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} md={3}>
                <Card sx={{ backgroundColor: '#161b22' }}>
                  <CardContent>
                    <Typography color="text.secondary" gutterBottom>Consensus</Typography>
                    <Chip 
                      label={diagnosis.consensus ? 'YES' : 'NO'} 
                      color={diagnosis.consensus ? 'success' : 'warning'}
                    />
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} md={3}>
                <Card sx={{ backgroundColor: '#161b22' }}>
                  <CardContent>
                    <Typography color="text.secondary" gutterBottom>Confidence</Typography>
                    <Typography variant="h5">
                      {((diagnosis.confidence || 0) * 100).toFixed(0)}%
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>

            <Accordion sx={{ mt: 2, backgroundColor: '#161b22' }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography>Agent Responses</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <List dense>
                  {Object.entries(diagnosis.agent_responses || {}).map(([agent, response]) => (
                    <ListItem key={agent}>
                      <ListItemText
                        primary={<Typography color="primary">{agent}</Typography>}
                        secondary={response}
                      />
                    </ListItem>
                  ))}
                </List>
              </AccordionDetails>
            </Accordion>

            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
              Diagnosis time: {diagnosis.diagnosis_time_seconds}s | 
              Events analyzed: {diagnosis.telemetry_summary?.events_collected || 0}
            </Typography>
          </Box>
        </Paper>
      )}
    </Box>
  )
}

export default ACITelemetry
