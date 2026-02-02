import { useState, useEffect } from 'react'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import { Box, AppBar, Toolbar, Typography, Tabs, Tab, Container, IconButton, Menu, MenuItem } from '@mui/material'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import SettingsIcon from '@mui/icons-material/Settings'
import ChatPanel from './components/ChatPanel'
import EKSStatus from './components/EKSStatus'
import Anomalies from './components/Anomalies'
import RCAReports from './components/RCAReports'
import PluginManager from './components/PluginManager'
import ClusterSelector from './components/ClusterSelector'
import ACITelemetry from './components/ACITelemetry'

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#ff9900', // AWS Orange
    },
    secondary: {
      main: '#232f3e', // AWS Dark Blue
    },
    background: {
      default: '#0d1117',
      paper: '#161b22',
    },
  },
})

function App() {
  const [activeTab, setActiveTab] = useState(0)
  const [activeCluster, setActiveCluster] = useState(null)
  const [settingsAnchor, setSettingsAnchor] = useState(null)
  
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    // Fetch initial active cluster
    fetch(`${API_URL}/api/clusters/active`)
      .then(res => res.json())
      .then(data => setActiveCluster(data))
      .catch(console.error)
  }, [])

  const handleTabChange = (event, newValue) => {
    setActiveTab(newValue)
  }

  const handleClusterChange = (cluster) => {
    setActiveCluster(cluster)
  }

  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <AppBar position="static" sx={{ backgroundColor: '#232f3e' }}>
          <Toolbar>
            <SmartToyIcon sx={{ mr: 2, color: '#ff9900' }} />
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              AgenticAIOps Dashboard
            </Typography>
            
            {/* Cluster Selector */}
            <Box sx={{ mr: 2 }}>
              <ClusterSelector onClusterChange={handleClusterChange} />
            </Box>
            
            {/* Settings Menu */}
            <IconButton
              onClick={(e) => setSettingsAnchor(e.currentTarget)}
              sx={{ color: '#aaa' }}
            >
              <SettingsIcon />
            </IconButton>
            <Menu
              anchorEl={settingsAnchor}
              open={Boolean(settingsAnchor)}
              onClose={() => setSettingsAnchor(null)}
            >
              <MenuItem onClick={() => { setActiveTab(4); setSettingsAnchor(null); }}>
                🔌 Plugin Manager
              </MenuItem>
            </Menu>
          </Toolbar>
        </AppBar>

        <Box sx={{ borderBottom: 1, borderColor: 'divider', backgroundColor: '#161b22' }}>
          <Tabs 
            value={activeTab} 
            onChange={handleTabChange}
            textColor="primary"
            indicatorColor="primary"
          >
            <Tab label="💬 Chat" />
            <Tab label="📊 Status" />
            <Tab label="🔬 ACI Telemetry" />
            <Tab label="🚨 Anomalies" />
            <Tab label="📝 RCA Reports" />
            <Tab label="🔌 Plugins" />
          </Tabs>
        </Box>

        <Container maxWidth="xl" sx={{ flexGrow: 1, py: 2 }}>
          {activeTab === 0 && <ChatPanel activeCluster={activeCluster} />}
          {activeTab === 1 && <EKSStatus activeCluster={activeCluster} />}
          {activeTab === 2 && <ACITelemetry activeCluster={activeCluster} />}
          {activeTab === 3 && <Anomalies activeCluster={activeCluster} />}
          {activeTab === 4 && <RCAReports />}
          {activeTab === 5 && <PluginManager />}
        </Container>

        <Box component="footer" sx={{ py: 1, textAlign: 'center', backgroundColor: '#161b22' }}>
          <Typography variant="body2" color="text.secondary">
            AgenticAIOps © 2026 | Powered by Strands SDK + AWS Bedrock
            {activeCluster && ` | Active: ${activeCluster.name}`}
          </Typography>
        </Box>
      </Box>
    </ThemeProvider>
  )
}

export default App
