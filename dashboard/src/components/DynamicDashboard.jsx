import { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Statistic, Table, Progress, Alert, Tag, Button, Space, Dropdown, Modal, Input, message, Spin, Empty, Tooltip } from 'antd'
import { 
  PlusOutlined, 
  DragOutlined, 
  DeleteOutlined, 
  EditOutlined, 
  SettingOutlined,
  ReloadOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  ApiOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  ExpandOutlined,
  CompressOutlined,
  TableOutlined,
  DashboardOutlined,
} from '@ant-design/icons'

// Widget Types - Grafana-style
const WIDGET_TYPES = {
  STAT_CARD: 'stat-card',
  TABLE: 'table',
  ALERT_LIST: 'alert-list',
  PROGRESS_BAR: 'progress-bar',
  SERVICE_STATUS: 'service-status',
  RESOURCE_LIST: 'resource-list',
  CHART: 'chart',
}

// Default widget configurations
const DEFAULT_WIDGETS = {
  [WIDGET_TYPES.STAT_CARD]: {
    title: 'Statistic',
    value: 0,
    suffix: '',
    icon: 'cloud',
    color: '#06AC38',
  },
  [WIDGET_TYPES.TABLE]: {
    title: 'Data Table',
    columns: [],
    dataSource: [],
    api: '',
  },
  [WIDGET_TYPES.ALERT_LIST]: {
    title: 'Alerts',
    maxItems: 5,
    severity: 'all',
  },
  [WIDGET_TYPES.SERVICE_STATUS]: {
    title: 'Service Status',
    services: [],
  },
}

// Stat Card Widget
const StatCardWidget = ({ config, data }) => {
  const iconMap = {
    cloud: <CloudServerOutlined />,
    database: <DatabaseOutlined />,
    api: <ApiOutlined />,
    warning: <WarningOutlined />,
  }
  
  return (
    <Card size="small" style={{ height: '100%' }}>
      <Statistic 
        title={config.title}
        value={data?.value ?? config.value}
        suffix={config.suffix}
        prefix={iconMap[config.icon] || <CloudServerOutlined />}
        valueStyle={{ color: config.color }}
      />
    </Card>
  )
}

// Table Widget
const TableWidget = ({ config, data }) => {
  const columns = config.columns?.map(col => ({
    title: col.title || col,
    dataIndex: col.dataIndex || col.toLowerCase().replace(/\s+/g, '_'),
    key: col.key || col.toLowerCase().replace(/\s+/g, '_'),
    render: col.render,
  })) || []
  
  return (
    <Card title={config.title} size="small" style={{ height: '100%' }}>
      <Table 
        columns={columns}
        dataSource={data?.items || config.dataSource || []}
        size="small"
        pagination={{ pageSize: 5, size: 'small' }}
        scroll={{ y: 200 }}
      />
    </Card>
  )
}

// Alert List Widget
const AlertListWidget = ({ config, data }) => {
  const alerts = data?.alerts || []
  const severityColors = { high: 'red', medium: 'orange', low: 'green' }
  
  return (
    <Card title={config.title} size="small" style={{ height: '100%' }}>
      {alerts.length === 0 ? (
        <Empty description="No alerts" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ maxHeight: 200, overflow: 'auto' }}>
          {alerts.slice(0, config.maxItems || 5).map((alert, i) => (
            <Alert
              key={i}
              message={alert.title}
              description={alert.description}
              type={alert.severity === 'high' ? 'error' : alert.severity === 'medium' ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 8 }}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

// Service Status Widget
const ServiceStatusWidget = ({ config, data }) => {
  const services = data?.services || config.services || []
  
  const statusIcon = (status) => {
    if (status === 'healthy' || status === 'running') return <CheckCircleOutlined style={{ color: '#52c41a' }} />
    if (status === 'warning') return <WarningOutlined style={{ color: '#faad14' }} />
    return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
  }
  
  return (
    <Card title={config.title} size="small" style={{ height: '100%' }}>
      <div style={{ maxHeight: 200, overflow: 'auto' }}>
        {services.map((svc, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
            <span>{svc.name}</span>
            <Space>
              {statusIcon(svc.status)}
              <Tag color={svc.status === 'healthy' ? 'green' : svc.status === 'warning' ? 'orange' : 'red'}>
                {svc.status}
              </Tag>
            </Space>
          </div>
        ))}
      </div>
    </Card>
  )
}

// Progress Widget
const ProgressWidget = ({ config, data }) => {
  const percent = data?.percent ?? config.percent ?? 0
  const status = percent > 80 ? 'exception' : percent > 60 ? 'active' : 'success'
  
  return (
    <Card title={config.title} size="small" style={{ height: '100%' }}>
      <Progress 
        percent={percent} 
        status={status}
        format={(p) => `${p}%`}
      />
      {config.description && <div style={{ color: '#666', marginTop: 8 }}>{config.description}</div>}
    </Card>
  )
}

// Resource List Widget
const ResourceListWidget = ({ config, data }) => {
  const resources = data?.resources || []
  
  return (
    <Card title={config.title} size="small" style={{ height: '100%' }}>
      <div style={{ maxHeight: 200, overflow: 'auto' }}>
        {resources.length === 0 ? (
          <Empty description="No resources" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          resources.map((res, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <div style={{ fontWeight: 500 }}>{res.name || res.id}</div>
              <div style={{ fontSize: 12, color: '#666' }}>
                {res.type} • {res.region || 'N/A'}
                <Tag size="small" style={{ marginLeft: 8 }}>{res.status}</Tag>
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  )
}

// Widget Renderer - maps type to component
const WidgetRenderer = ({ widget, data, onEdit, onDelete }) => {
  const [isHovered, setIsHovered] = useState(false)
  
  const renderWidget = () => {
    switch (widget.type) {
      case WIDGET_TYPES.STAT_CARD:
        return <StatCardWidget config={widget.config} data={data} />
      case WIDGET_TYPES.TABLE:
        return <TableWidget config={widget.config} data={data} />
      case WIDGET_TYPES.ALERT_LIST:
        return <AlertListWidget config={widget.config} data={data} />
      case WIDGET_TYPES.SERVICE_STATUS:
        return <ServiceStatusWidget config={widget.config} data={data} />
      case WIDGET_TYPES.PROGRESS_BAR:
        return <ProgressWidget config={widget.config} data={data} />
      case WIDGET_TYPES.RESOURCE_LIST:
        return <ResourceListWidget config={widget.config} data={data} />
      default:
        return <Card><Empty description={`Unknown widget type: ${widget.type}`} /></Card>
    }
  }
  
  return (
    <div 
      style={{ position: 'relative', height: '100%' }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isHovered && (
        <div style={{ 
          position: 'absolute', 
          top: 4, 
          right: 4, 
          zIndex: 10,
          background: 'rgba(255,255,255,0.9)',
          borderRadius: 4,
          padding: 2,
        }}>
          <Space size={4}>
            <Tooltip title="Edit">
              <Button size="small" type="text" icon={<EditOutlined />} onClick={() => onEdit?.(widget)} />
            </Tooltip>
            <Tooltip title="Delete">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => onDelete?.(widget.id)} />
            </Tooltip>
          </Space>
        </div>
      )}
      {renderWidget()}
    </div>
  )
}

// Main Dynamic Dashboard Component
function DynamicDashboard({ apiUrl, initialLayout, onLayoutChange }) {
  const [layout, setLayout] = useState(initialLayout || { widgets: [], rows: [] })
  const [widgetData, setWidgetData] = useState({})
  const [loading, setLoading] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [addWidgetModal, setAddWidgetModal] = useState(false)
  
  // Fetch widget data from APIs
  const fetchWidgetData = useCallback(async () => {
    setLoading(true)
    const newData = {}
    
    for (const widget of layout.widgets) {
      if (widget.config?.api) {
        try {
          const response = await fetch(`${apiUrl}${widget.config.api}`)
          const data = await response.json()
          newData[widget.id] = data
        } catch (error) {
          console.error(`Failed to fetch data for widget ${widget.id}:`, error)
        }
      }
    }
    
    setWidgetData(newData)
    setLoading(false)
  }, [layout.widgets, apiUrl])
  
  useEffect(() => {
    if (layout.widgets.length > 0) {
      fetchWidgetData()
    }
  }, [layout.widgets.length])
  
  // Add widget
  const handleAddWidget = (type) => {
    const newWidget = {
      id: `widget-${Date.now()}`,
      type,
      config: { ...DEFAULT_WIDGETS[type] },
      span: type === WIDGET_TYPES.TABLE ? 24 : 8,
    }
    
    setLayout(prev => ({
      ...prev,
      widgets: [...prev.widgets, newWidget],
    }))
    setAddWidgetModal(false)
    message.success('Widget added')
  }
  
  // Delete widget
  const handleDeleteWidget = (widgetId) => {
    setLayout(prev => ({
      ...prev,
      widgets: prev.widgets.filter(w => w.id !== widgetId),
    }))
    message.success('Widget removed')
  }
  
  // Edit widget
  const handleEditWidget = (widget) => {
    // TODO: Open edit modal
    message.info('Edit widget: ' + widget.config.title)
  }
  
  // Apply layout from Agent
  const applyAgentLayout = (agentLayout) => {
    setLayout(agentLayout)
    onLayoutChange?.(agentLayout)
  }
  
  // Widget type menu for adding
  const addWidgetMenu = {
    items: [
      { key: WIDGET_TYPES.STAT_CARD, label: '📊 Stat Card', icon: <DashboardOutlined /> },
      { key: WIDGET_TYPES.TABLE, label: '📋 Table', icon: <TableOutlined /> },
      { key: WIDGET_TYPES.ALERT_LIST, label: '⚠️ Alert List', icon: <WarningOutlined /> },
      { key: WIDGET_TYPES.SERVICE_STATUS, label: '🟢 Service Status', icon: <CheckCircleOutlined /> },
      { key: WIDGET_TYPES.PROGRESS_BAR, label: '📈 Progress Bar', icon: <SyncOutlined /> },
      { key: WIDGET_TYPES.RESOURCE_LIST, label: '☁️ Resource List', icon: <CloudServerOutlined /> },
    ],
    onClick: ({ key }) => handleAddWidget(key),
  }
  
  return (
    <div style={{ padding: 16 }}>
      {/* Toolbar */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Dropdown menu={addWidgetMenu} trigger={['click']}>
            <Button type="primary" icon={<PlusOutlined />} style={{ background: '#06AC38' }}>
              Add Widget
            </Button>
          </Dropdown>
          <Button 
            icon={editMode ? <CompressOutlined /> : <ExpandOutlined />}
            onClick={() => setEditMode(!editMode)}
          >
            {editMode ? 'Done Editing' : 'Edit Layout'}
          </Button>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchWidgetData} loading={loading}>
            Refresh
          </Button>
        </Space>
      </div>
      
      {/* Dashboard Grid */}
      {layout.widgets.length === 0 ? (
        <Card style={{ textAlign: 'center', padding: 40 }}>
          <Empty 
            description={
              <span>
                No widgets yet. Click <strong>Add Widget</strong> or use the AI Assistant to build your dashboard!
                <br />
                <small style={{ color: '#999' }}>Try: "Add an EC2 instances table" in chat</small>
              </span>
            }
          />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {layout.widgets.map(widget => (
            <Col key={widget.id} span={widget.span || 8}>
              <div style={{ 
                minHeight: widget.type === WIDGET_TYPES.TABLE ? 300 : 150,
                border: editMode ? '2px dashed #06AC38' : 'none',
                borderRadius: 4,
              }}>
                <WidgetRenderer 
                  widget={widget}
                  data={widgetData[widget.id]}
                  onEdit={handleEditWidget}
                  onDelete={handleDeleteWidget}
                />
              </div>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}

// Missing import for TableOutlined - moved to top

export default DynamicDashboard
export { WIDGET_TYPES, DEFAULT_WIDGETS }
