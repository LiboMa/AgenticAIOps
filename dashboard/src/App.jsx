import { useState } from 'react'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import { Box, AppBar, Toolbar, Typography, Tabs, Tab, Container } from '@mui/material'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import ChatPanel from './components/ChatPanel'
import EKSStatus from './components/EKSStatus'
import Anomalies from './components/Anomalies'
import RCAReports from './components/RCAReports'

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

  const handleTabChange = (event, newValue) => {
    setActiveTab(newValue)
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
            <Typography variant="body2" sx={{ color: '#aaa' }}>
              Cluster: testing-cluster | Region: ap-southeast-1
            </Typography>
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
            <Tab label="📊 EKS Status" />
            <Tab label="🚨 Anomalies" />
            <Tab label="📝 RCA Reports" />
          </Tabs>
        </Box>

        <Container maxWidth="xl" sx={{ flexGrow: 1, py: 2 }}>
          {activeTab === 0 && <ChatPanel />}
          {activeTab === 1 && <EKSStatus />}
          {activeTab === 2 && <Anomalies />}
          {activeTab === 3 && <RCAReports />}
        </Container>

        <Box component="footer" sx={{ py: 1, textAlign: 'center', backgroundColor: '#161b22' }}>
          <Typography variant="body2" color="text.secondary">
            AgenticAIOps © 2026 | Powered by Strands SDK + AWS Bedrock
          </Typography>
        </Box>
      </Box>
    </ThemeProvider>
  )
}

export default App
