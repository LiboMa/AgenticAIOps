import { useState } from 'react'
import { Card, Button, Input, Space, message, Spin, Descriptions, Tag, Steps, Timeline } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import {
  SearchOutlined,
  BugOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'

function Diagnosis({ apiUrl }) {
  const [namespace, setNamespace] = useState('stress-test')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleDiagnosis = async () => {
    setLoading(true)
    setResult(null)
    
    try {
      const res = await fetch(`${apiUrl}/api/aci/diagnosis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ namespace }),
      })
      const data = await res.json()
      
      if (data.error) {
        message.error(data.error)
      } else {
        setResult(data.report || data)
        message.success('Diagnosis completed')
      }
    } catch (err) {
      message.error('Diagnosis request failed')
    } finally {
      setLoading(false)
    }
  }

  const renderDiagnosisResult = () => {
    if (!result) return null

    return (
      <Space direction="vertical" size="large" style={{ width: '100%', marginTop: 24 }}>
        {/* Summary */}
        <ProCard
          title="Diagnosis Summary"
          style={{ background: '#fff' }}
        >
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="Namespace">{result.namespace || namespace}</Descriptions.Item>
            <Descriptions.Item label="Diagnosis Time">
              {result.timestamp ? new Date(result.timestamp).toLocaleString() : new Date().toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="Issue Count">
              <Tag color={result.issues_count > 0 ? 'red' : 'green'}>
                {result.issues_count || 0} issues
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Status">
              <Tag color={result.status === 'healthy' ? 'green' : 'orange'}>
                {result.status || 'completed'}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
        </ProCard>

        {/* Root Cause */}
        {result.root_cause && (
          <ProCard title="Root Cause Analysis" style={{ background: '#fff' }}>
            <div style={{ 
              background: '#f5f5f5', 
              padding: 16, 
              borderRadius: 8,
              border: '1px solid #e8e8e8',
            }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#333' }}>
                {typeof result.root_cause === 'string' 
                  ? result.root_cause 
                  : JSON.stringify(result.root_cause, null, 2)}
              </pre>
            </div>
          </ProCard>
        )}

        {/* Recommendations */}
        {result.recommendations && (
          <ProCard title="Remediation Steps" style={{ background: '#fff' }}>
            <Timeline
              items={
                (Array.isArray(result.recommendations) 
                  ? result.recommendations 
                  : [result.recommendations]
                ).map((rec, idx) => ({
                  color: idx === 0 ? 'blue' : 'gray',
                  children: (
                    <div>
                      <strong>Step {idx + 1}</strong>
                      <p style={{ margin: '8px 0 0' }}>{rec}</p>
                    </div>
                  ),
                }))
              }
            />
          </ProCard>
        )}

        {/* Raw Data */}
        <ProCard
          title="Raw Data"
          collapsible
          defaultCollapsed
          style={{ background: '#fff' }}
        >
          <pre style={{ 
            background: '#f5f5f5', 
            padding: 16, 
            borderRadius: 8,
            overflow: 'auto',
            maxHeight: 400,
            color: '#333',
            fontSize: 12,
          }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </ProCard>
      </Space>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Diagnosis Input */}
      <ProCard
        title={
          <Space>
            <ExperimentOutlined />
            AI Diagnostics
          </Space>
        }
        style={{ background: '#fff' }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <label style={{ color: '#666', marginBottom: 8, display: 'block' }}>
              Target Namespace
            </label>
            <Input
              placeholder="Enter namespace to diagnose"
              value={namespace}
              onChange={(e) => setNamespace(e.target.value)}
              style={{ width: 300 }}
              prefix={<SearchOutlined style={{ color: '#999' }} />}
            />
          </div>

          <Button
            type="primary"
            icon={loading ? <LoadingOutlined /> : <BugOutlined />}
            onClick={handleDiagnosis}
            loading={loading}
            size="large"
            style={{ background: '#06AC38', borderColor: '#06AC38' }}
          >
            {loading ? 'Analyzing...' : 'Start Diagnosis'}
          </Button>

          {loading && (
            <Steps
              current={1}
              size="small"
              items={[
                { title: 'Collect Data', status: 'finish' },
                { title: 'Analyze Issues', status: 'process' },
                { title: 'Generate Report', status: 'wait' },
              ]}
            />
          )}
        </Space>
      </ProCard>

      {/* Results */}
      {renderDiagnosisResult()}
    </Space>
  )
}

export default Diagnosis
