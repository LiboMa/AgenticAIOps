import { useState, useEffect } from 'react'
import {
  Box, Paper, Typography, Card, CardContent, CardActions,
  Button, Chip, Grid, IconButton, Tooltip, Dialog,
  DialogTitle, DialogContent, DialogActions, Divider
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import DescriptionIcon from '@mui/icons-material/Description'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function RCAReports() {
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedReport, setSelectedReport] = useState(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const fetchReports = async () => {
    setLoading(true)
    try {
      const response = await axios.get(`${API_URL}/api/rca/reports`)
      setReports(response.data.reports || [])
    } catch (error) {
      // Mock data for demo
      setReports([
        {
          id: 'RCA-2026-0201-001',
          title: 'OOM Killed - oom-app',
          status: 'resolved',
          severity: 'critical',
          createdAt: '2026-02-01T14:30:00Z',
          resolvedAt: '2026-02-01T15:45:00Z',
          rootCause: 'Memory limit set to 64Mi, application requires minimum 256Mi during startup',
          symptoms: [
            'Pod status: OOMKilled',
            'Restart count: 8',
            'Last state: terminated with exit code 137'
          ],
          diagnosis: {
            intent: 'diagnose',
            confidence: 0.95,
            votes: { 'oom': 3 }
          },
          solution: 'Increased memory limits from 64Mi to 256Mi in deployment spec',
          commands: [
            'kubectl patch deployment oom-app -n faulty-apps -p \'{"spec":{"template":{"spec":{"containers":[{"name":"oom-app","resources":{"limits":{"memory":"256Mi"}}}]}}}}\''
          ]
        },
        {
          id: 'RCA-2026-0201-002',
          title: 'CrashLoopBackOff - crashloop-app',
          status: 'investigating',
          severity: 'critical',
          createdAt: '2026-02-01T15:00:00Z',
          resolvedAt: null,
          rootCause: 'Application exits immediately due to missing required environment variable',
          symptoms: [
            'Pod status: CrashLoopBackOff',
            'Restart count: 15',
            'Exit code: 1 (application error)'
          ],
          diagnosis: {
            intent: 'diagnose',
            confidence: 0.85,
            votes: { 'crashloop': 2, 'config': 1 }
          },
          solution: 'Pending - Need to add missing DATABASE_URL environment variable',
          commands: []
        },
        {
          id: 'RCA-2026-0131-003',
          title: 'High Latency - shop-api',
          status: 'resolved',
          severity: 'warning',
          createdAt: '2026-01-31T10:00:00Z',
          resolvedAt: '2026-01-31T11:30:00Z',
          rootCause: 'Database connection pool exhausted under high load',
          symptoms: [
            'P99 latency: 5000ms (threshold: 500ms)',
            'Error rate: 15%',
            'Database connections: 100/100'
          ],
          diagnosis: {
            intent: 'diagnose',
            confidence: 0.90,
            votes: { 'resource': 2, 'network': 1 }
          },
          solution: 'Increased connection pool size and enabled HPA for shop-api',
          commands: [
            'kubectl scale deployment shop-api -n onlineshop --replicas=5'
          ]
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReports()
  }, [])

  const handleViewReport = (report) => {
    setSelectedReport(report)
    setDialogOpen(true)
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'resolved': return 'success'
      case 'investigating': return 'warning'
      case 'open': return 'error'
      default: return 'default'
    }
  }

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical': return 'error'
      case 'warning': return 'warning'
      default: return 'info'
    }
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">RCA Reports</Typography>
        <Tooltip title="Refresh">
          <IconButton onClick={fetchReports} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      <Grid container spacing={2}>
        {reports.map((report) => (
          <Grid item xs={12} md={6} lg={4} key={report.id}>
            <Card sx={{ backgroundColor: '#21262d', height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                  <Chip 
                    label={report.status} 
                    color={getStatusColor(report.status)} 
                    size="small"
                    icon={report.status === 'resolved' ? <CheckCircleIcon /> : <ErrorIcon />}
                  />
                  <Chip 
                    label={report.severity} 
                    color={getSeverityColor(report.severity)} 
                    size="small" 
                    variant="outlined"
                  />
                </Box>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  {report.id}
                </Typography>
                <Typography variant="h6" sx={{ mb: 1 }}>
                  {report.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  {report.rootCause?.substring(0, 100)}...
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Created: {new Date(report.createdAt).toLocaleString()}
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  size="small" 
                  startIcon={<DescriptionIcon />}
                  onClick={() => handleViewReport(report)}
                >
                  View Report
                </Button>
              </CardActions>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Report Detail Dialog */}
      <Dialog 
        open={dialogOpen} 
        onClose={() => setDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        {selectedReport && (
          <>
            <DialogTitle>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h6">{selectedReport.title}</Typography>
                <Chip 
                  label={selectedReport.status} 
                  color={getStatusColor(selectedReport.status)} 
                  size="small"
                />
              </Box>
              <Typography variant="subtitle2" color="text.secondary">
                {selectedReport.id}
              </Typography>
            </DialogTitle>
            <DialogContent dividers>
              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                Root Cause
              </Typography>
              <Typography variant="body2" paragraph>
                {selectedReport.rootCause}
              </Typography>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                Symptoms
              </Typography>
              <Box component="ul" sx={{ pl: 2 }}>
                {selectedReport.symptoms?.map((s, i) => (
                  <li key={i}>
                    <Typography variant="body2">{s}</Typography>
                  </li>
                ))}
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                AI Diagnosis
              </Typography>
              <Typography variant="body2">
                Intent: {selectedReport.diagnosis?.intent} | 
                Confidence: {(selectedReport.diagnosis?.confidence * 100).toFixed(0)}%
              </Typography>
              <Typography variant="body2">
                Votes: {JSON.stringify(selectedReport.diagnosis?.votes)}
              </Typography>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle1" gutterBottom fontWeight="bold">
                Solution
              </Typography>
              <Typography variant="body2" paragraph>
                {selectedReport.solution}
              </Typography>

              {selectedReport.commands?.length > 0 && (
                <>
                  <Typography variant="subtitle2" gutterBottom>
                    Commands Applied:
                  </Typography>
                  <Paper sx={{ p: 1, backgroundColor: '#0d1117' }}>
                    {selectedReport.commands.map((cmd, i) => (
                      <Typography 
                        key={i} 
                        variant="body2" 
                        sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}
                      >
                        $ {cmd}
                      </Typography>
                    ))}
                  </Paper>
                </>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setDialogOpen(false)}>Close</Button>
              <Button variant="contained" color="primary">Export PDF</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Box>
  )
}

export default RCAReports
