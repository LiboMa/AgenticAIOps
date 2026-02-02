import { useState, useEffect, useCallback } from 'react'
import {
  Box, Paper, Typography, Grid, Chip, Button,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Dialog, DialogTitle, DialogContent, DialogActions,
  IconButton, Tooltip, CircularProgress, Alert, Snackbar,
  Card, CardContent, LinearProgress, Collapse
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import WarningIcon from '@mui/icons-material/Warning'
import BuildIcon from '@mui/icons-material/Build'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import HistoryIcon from '@mui/icons-material/History'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Severity color mapping
const severityColors = {
  low: '#4caf50',
  medium: '#ff9800',
  high: '#f44336',
  critical: '#d32f2f',
}

// Status icons
const statusIcons = {
  open: <ErrorIcon sx={{ color: '#f44336' }} />,
  in_progress: <BuildIcon sx={{ color: '#ff9800' }} />,
  resolved: <CheckCircleIcon sx={{ color: '#4caf50' }} />,
  closed: <CheckCircleIcon sx={{ color: '#888' }} />,
}

function IssueCenter({ activeCluster }) {
  const [issues, setIssues] = useState([])
  const [dashboardData, setDashboardData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [fixInProgress, setFixInProgress] = useState({})
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' })
  const [expandedRows, setExpandedRows] = useState({})

  // Fetch issues
  const fetchIssues = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_URL}/api/issues?limit=50`)
      if (!response.ok) throw new Error('Failed to fetch issues')
      const data = await response.json()
      setIssues(data.issues || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Fetch dashboard data
  const fetchDashboard = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/issues/dashboard`)
      if (!response.ok) throw new Error('Failed to fetch dashboard')
      const data = await response.json()
      setDashboardData(data)
    } catch (err) {
      console.error('Dashboard fetch error:', err)
    }
  }, [])

  useEffect(() => {
    fetchIssues()
    fetchDashboard()
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(() => {
      fetchIssues()
      fetchDashboard()
    }, 30000)
    
    return () => clearInterval(interval)
  }, [fetchIssues, fetchDashboard])

  // Handle auto-fix
  const handleAutoFix = async (issue) => {
    setFixInProgress(prev => ({ ...prev, [issue.id]: true }))
    
    try {
      const response = await fetch(`${API_URL}/api/issues/${issue.id}/fix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      
      if (!response.ok) throw new Error('Fix request failed')
      
      const result = await response.json()
      
      setSnackbar({
        open: true,
        message: `Auto-fix initiated: ${result.execution_id || 'Runbook started'}`,
        severity: 'success',
      })
      
      // Refresh issues after fix
      setTimeout(fetchIssues, 2000)
      
    } catch (err) {
      setSnackbar({
        open: true,
        message: `Fix failed: ${err.message}`,
        severity: 'error',
      })
    } finally {
      setFixInProgress(prev => ({ ...prev, [issue.id]: false }))
    }
  }

  // Handle resolve
  const handleResolve = async (issueId) => {
    try {
      const response = await fetch(`${API_URL}/api/issues/${issueId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'resolved' }),
      })
      
      if (!response.ok) throw new Error('Resolve failed')
      
      setSnackbar({
        open: true,
        message: 'Issue resolved',
        severity: 'success',
      })
      
      fetchIssues()
      setDialogOpen(false)
      
    } catch (err) {
      setSnackbar({
        open: true,
        message: `Resolve failed: ${err.message}`,
        severity: 'error',
      })
    }
  }

  // Toggle row expansion
  const toggleRow = (id) => {
    setExpandedRows(prev => ({ ...prev, [id]: !prev[id] }))
  }

  // Format timestamp
  const formatTime = (timestamp) => {
    if (!timestamp) return '-'
    return new Date(timestamp).toLocaleString()
  }

  // Dashboard summary cards
  const DashboardSummary = () => {
    if (!dashboardData) return null

    const { status_counts = {}, severity_counts = {}, recent_count = 0 } = dashboardData

    return (
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={3}>
          <Card sx={{ bgcolor: '#1a1a2e' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Open Issues
              </Typography>
              <Typography variant="h4" sx={{ color: '#f44336' }}>
                {status_counts.open || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ bgcolor: '#1a1a2e' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                In Progress
              </Typography>
              <Typography variant="h4" sx={{ color: '#ff9800' }}>
                {status_counts.in_progress || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ bgcolor: '#1a1a2e' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Resolved (24h)
              </Typography>
              <Typography variant="h4" sx={{ color: '#4caf50' }}>
                {status_counts.resolved || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card sx={{ bgcolor: '#1a1a2e' }}>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                High Severity
              </Typography>
              <Typography variant="h4" sx={{ color: '#d32f2f' }}>
                {severity_counts.high || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    )
  }

  // Issue detail dialog
  const IssueDetailDialog = () => {
    if (!selectedIssue) return null

    return (
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {statusIcons[selectedIssue.status]}
            <Typography variant="h6">{selectedIssue.title}</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">ID</Typography>
              <Typography>{selectedIssue.id}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">Status</Typography>
              <Chip
                label={selectedIssue.status}
                size="small"
                sx={{ bgcolor: selectedIssue.status === 'open' ? '#f44336' : '#4caf50' }}
              />
            </Grid>
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">Severity</Typography>
              <Chip
                label={selectedIssue.severity}
                size="small"
                sx={{ bgcolor: severityColors[selectedIssue.severity] }}
              />
            </Grid>
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">Namespace</Typography>
              <Typography>{selectedIssue.namespace}</Typography>
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" color="text.secondary">Resource</Typography>
              <Typography>{selectedIssue.resource_type}/{selectedIssue.resource_name}</Typography>
            </Grid>
            <Grid item xs={12}>
              <Typography variant="subtitle2" color="text.secondary">Description</Typography>
              <Typography>{selectedIssue.description || '-'}</Typography>
            </Grid>
            {selectedIssue.root_cause && (
              <Grid item xs={12}>
                <Typography variant="subtitle2" color="text.secondary">Root Cause</Typography>
                <Paper sx={{ p: 1, bgcolor: '#0d1117' }}>
                  <Typography variant="body2">{selectedIssue.root_cause}</Typography>
                </Paper>
              </Grid>
            )}
            {selectedIssue.remediation && (
              <Grid item xs={12}>
                <Typography variant="subtitle2" color="text.secondary">Remediation</Typography>
                <Paper sx={{ p: 1, bgcolor: '#0d1117' }}>
                  <Typography variant="body2">{selectedIssue.remediation}</Typography>
                </Paper>
              </Grid>
            )}
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">Created</Typography>
              <Typography variant="body2">{formatTime(selectedIssue.created_at)}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="subtitle2" color="text.secondary">Updated</Typography>
              <Typography variant="body2">{formatTime(selectedIssue.updated_at)}</Typography>
            </Grid>
            {selectedIssue.fix_attempts && selectedIssue.fix_attempts.length > 0 && (
              <Grid item xs={12}>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                  <HistoryIcon sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'middle' }} />
                  Fix Attempts
                </Typography>
                {selectedIssue.fix_attempts.map((attempt, idx) => (
                  <Paper key={idx} sx={{ p: 1, mb: 1, bgcolor: '#0d1117' }}>
                    <Typography variant="body2">
                      {attempt.action} - {attempt.success ? '✅ Success' : '❌ Failed'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {formatTime(attempt.timestamp)}
                    </Typography>
                  </Paper>
                ))}
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          {selectedIssue.status === 'open' && selectedIssue.auto_fixable && (
            <Button
              startIcon={<AutoFixHighIcon />}
              onClick={() => handleAutoFix(selectedIssue)}
              color="warning"
              disabled={fixInProgress[selectedIssue.id]}
            >
              Auto Fix
            </Button>
          )}
          {selectedIssue.status !== 'resolved' && (
            <Button
              onClick={() => handleResolve(selectedIssue.id)}
              color="success"
            >
              Mark Resolved
            </Button>
          )}
          <Button onClick={() => setDialogOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    )
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5">
          🎯 Issue Center
        </Typography>
        <Tooltip title="Refresh">
          <IconButton onClick={fetchIssues} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Error alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Dashboard Summary */}
      <DashboardSummary />

      {/* Issues Table */}
      <Paper sx={{ bgcolor: '#161b22' }}>
        {loading && <LinearProgress />}
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={40}></TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Severity</TableCell>
                <TableCell>Title</TableCell>
                <TableCell>Namespace</TableCell>
                <TableCell>Resource</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {issues.map((issue) => (
                <>
                  <TableRow 
                    key={issue.id}
                    hover
                    sx={{ 
                      cursor: 'pointer',
                      '&:hover': { bgcolor: '#1a1a2e' }
                    }}
                  >
                    <TableCell>
                      <IconButton size="small" onClick={() => toggleRow(issue.id)}>
                        {expandedRows[issue.id] ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                    </TableCell>
                    <TableCell>
                      <Chip
                        icon={statusIcons[issue.status]}
                        label={issue.status}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={issue.severity}
                        size="small"
                        sx={{ 
                          bgcolor: severityColors[issue.severity],
                          color: 'white',
                        }}
                      />
                    </TableCell>
                    <TableCell 
                      onClick={() => { setSelectedIssue(issue); setDialogOpen(true); }}
                    >
                      {issue.title}
                    </TableCell>
                    <TableCell>{issue.namespace}</TableCell>
                    <TableCell>
                      <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>
                        {issue.resource_type}/{issue.resource_name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {formatTime(issue.created_at)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {issue.status === 'open' && issue.auto_fixable && (
                        <Tooltip title="Auto Fix">
                          <IconButton 
                            size="small"
                            onClick={(e) => { e.stopPropagation(); handleAutoFix(issue); }}
                            disabled={fixInProgress[issue.id]}
                            color="warning"
                          >
                            {fixInProgress[issue.id] ? (
                              <CircularProgress size={20} />
                            ) : (
                              <AutoFixHighIcon />
                            )}
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                  
                  {/* Expanded row content */}
                  <TableRow>
                    <TableCell colSpan={8} sx={{ py: 0 }}>
                      <Collapse in={expandedRows[issue.id]}>
                        <Box sx={{ p: 2, bgcolor: '#0d1117' }}>
                          <Grid container spacing={2}>
                            {issue.description && (
                              <Grid item xs={12}>
                                <Typography variant="subtitle2" color="text.secondary">
                                  Description
                                </Typography>
                                <Typography variant="body2">{issue.description}</Typography>
                              </Grid>
                            )}
                            {issue.root_cause && (
                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle2" color="text.secondary">
                                  Root Cause
                                </Typography>
                                <Typography variant="body2">{issue.root_cause}</Typography>
                              </Grid>
                            )}
                            {issue.remediation && (
                              <Grid item xs={12} md={6}>
                                <Typography variant="subtitle2" color="text.secondary">
                                  Remediation
                                </Typography>
                                <Typography variant="body2">{issue.remediation}</Typography>
                              </Grid>
                            )}
                          </Grid>
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </>
              ))}
              
              {issues.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    <Typography color="text.secondary" sx={{ py: 4 }}>
                      ✨ No issues found - System is healthy!
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Detail Dialog */}
      <IssueDetailDialog />

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}

export default IssueCenter
