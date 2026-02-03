import { useState } from 'react'
import { Card, Button, Input, Space, message, Spin, Descriptions, Tag, Steps, Timeline, Row, Col, Typography, Select } from 'antd'
import { ProCard } from '@ant-design/pro-components'
import {
  SearchOutlined,
  BugOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'

const { Title, Text } = Typography

function Diagnosis({ apiUrl }) {
  const [namespace, setNamespace] = useState('stress-test')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleDiagnosis = async () => {
    setLoading(true)
    setResult(null)
    
    try {
      const res = await fetch(`${apiUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: `Diagnose all issues in ${namespace} namespace. Check for OOMKilled, CrashLoopBackOff, ImagePullBackOff, and other common issues.` }),
      })
      const data = await res.json()
      
      if (data.error) {
        message.error(data.error)
      } else {
        setResult({ response: data.response, namespace, timestamp: new Date().toISOString() })
        message.success('Diagnosis completed')
      }
    } catch (err) {
      message.error('Diagnosis request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>AI Diagnostics</Title>
        <Text type="secondary">Analyze and troubleshoot cluster issues with AI</Text>
      </div>

      <Row gutter={[16, 16]}>
        {/* Diagnostics Panel - Full Width */}
        <Col span={24}>
          <Card
            bordered={false}
            title={
              <Space>
                <ExperimentOutlined style={{ color: '#06AC38' }} />
                Quick Diagnosis
              </Space>
            }
          >
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div>
                <label style={{ color: '#666', marginBottom: 8, display: 'block' }}>
                  Target Namespace
                </label>
                <Space wrap>
                  <Select
                    value={namespace}
                    onChange={setNamespace}
                    style={{ width: 200, minWidth: 150 }}
                    options={[
                      { value: 'stress-test', label: 'stress-test' },
                      { value: 'default', label: 'default' },
                      { value: 'production', label: 'production' },
                      { value: 'kube-system', label: 'kube-system' },
                    ]}
                  />
                  <Button
                    type="primary"
                    icon={loading ? <LoadingOutlined /> : <BugOutlined />}
                    onClick={handleDiagnosis}
                    loading={loading}
                    size="large"
                    style={{ background: '#06AC38', borderColor: '#06AC38' }}
                  >
                    {loading ? 'Analyzing...' : 'Run Diagnosis'}
                  </Button>
                </Space>
              </div>

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
          </Card>
        </Col>

        {/* Results - Full Width */}
        {result && (
          <Col span={24}>
            <Card bordered={false} title="Diagnosis Results">
              <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="Namespace">
                  <Tag color="blue">{result.namespace}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="Time">
                  {new Date(result.timestamp).toLocaleString()}
                </Descriptions.Item>
              </Descriptions>
              <div style={{ 
                background: '#f5f5f5', 
                padding: 16, 
                borderRadius: 8,
                maxHeight: 600,
                overflow: 'auto',
              }}>
                <div className="markdown-content" style={{ fontSize: 14, lineHeight: 1.6 }}>
                  <ReactMarkdown>{result.response}</ReactMarkdown>
                </div>
              </div>
            </Card>
          </Col>
        )}
      </Row>
    </div>
  )
}

export default Diagnosis
