import { useState, useEffect } from 'react';

const PLUGIN_ICONS = {
  eks: '☸️',
  ec2: '🖥️',
  lambda: 'λ',
  hpc: '🖧'
};

export default function PluginManager() {
  const [plugins, setPlugins] = useState([]);
  const [availableTypes, setAvailableTypes] = useState([]);
  const [clusters, setClusters] = useState([]);
  const [activeCluster, setActiveCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddPlugin, setShowAddPlugin] = useState(false);
  const [newPlugin, setNewPlugin] = useState({ type: 'eks', name: '', regions: 'ap-southeast-1' });

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchPlugins();
    fetchClusters();
  }, []);

  const fetchPlugins = async () => {
    try {
      const res = await fetch(`${API_URL}/api/plugins`);
      const data = await res.json();
      setPlugins(data.plugins || []);
      setAvailableTypes(data.available_types || []);
    } catch (error) {
      console.error('Failed to fetch plugins:', error);
    }
  };

  const fetchClusters = async () => {
    try {
      const res = await fetch(`${API_URL}/api/clusters`);
      const data = await res.json();
      setClusters(data.clusters || []);
      setActiveCluster(data.active_cluster);
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch clusters:', error);
      setLoading(false);
    }
  };

  const handleEnablePlugin = async (pluginId, enabled) => {
    try {
      const action = enabled ? 'enable' : 'disable';
      await fetch(`${API_URL}/api/plugins/${pluginId}/${action}`, { method: 'POST' });
      fetchPlugins();
      fetchClusters();
    } catch (error) {
      console.error('Failed to toggle plugin:', error);
    }
  };

  const handleAddPlugin = async () => {
    try {
      const res = await fetch(`${API_URL}/api/plugins`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plugin_type: newPlugin.type,
          name: newPlugin.name || `${newPlugin.type.toUpperCase()} Plugin`,
          config: { regions: newPlugin.regions.split(',').map(r => r.trim()) }
        })
      });
      if (res.ok) {
        setShowAddPlugin(false);
        setNewPlugin({ type: 'eks', name: '', regions: 'ap-southeast-1' });
        fetchPlugins();
        fetchClusters();
      }
    } catch (error) {
      console.error('Failed to add plugin:', error);
    }
  };

  const handleActivateCluster = async (clusterId) => {
    try {
      await fetch(`${API_URL}/api/clusters/${clusterId}/activate`, { method: 'POST' });
      fetchClusters();
    } catch (error) {
      console.error('Failed to activate cluster:', error);
    }
  };

  const handleDeletePlugin = async (pluginId) => {
    if (!confirm('Are you sure you want to delete this plugin?')) return;
    try {
      await fetch(`${API_URL}/api/plugins/${pluginId}`, { method: 'DELETE' });
      fetchPlugins();
      fetchClusters();
    } catch (error) {
      console.error('Failed to delete plugin:', error);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Plugin Manager</h2>
        <button
          onClick={() => setShowAddPlugin(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center gap-2"
        >
          <span>➕</span> Add Plugin
        </button>
      </div>

      {/* Active Cluster Banner */}
      {activeCluster && (
        <div className="bg-gradient-to-r from-blue-500 to-blue-600 rounded-lg p-4 text-white">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm opacity-75">Active Cluster</span>
              <h3 className="text-xl font-bold flex items-center gap-2">
                {PLUGIN_ICONS[activeCluster.plugin_type]} {activeCluster.name}
              </h3>
              <span className="text-sm opacity-75">{activeCluster.region}</span>
            </div>
            <div className="text-right">
              <span className="text-sm opacity-75">Type</span>
              <p className="font-semibold">{activeCluster.plugin_type.toUpperCase()}</p>
            </div>
          </div>
        </div>
      )}

      {/* Plugins Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {plugins.map(plugin => (
          <div
            key={plugin.plugin_id}
            className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 border-l-4 ${
              plugin.status === 'enabled' ? 'border-green-500' : 'border-gray-400'
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <span className="text-3xl">{plugin.icon}</span>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-white">{plugin.name}</h3>
                  <p className="text-sm text-gray-500">{plugin.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleEnablePlugin(plugin.plugin_id, plugin.status !== 'enabled')}
                  className={`px-3 py-1 rounded text-sm ${
                    plugin.status === 'enabled'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {plugin.status === 'enabled' ? '✓ Enabled' : 'Disabled'}
                </button>
                <button
                  onClick={() => handleDeletePlugin(plugin.plugin_id)}
                  className="p-1 text-red-500 hover:bg-red-50 rounded"
                >
                  🗑️
                </button>
              </div>
            </div>
            <div className="mt-3 text-sm text-gray-500">
              <span>Tools: {plugin.tools_count}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Clusters Section */}
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Clusters & Resources ({clusters.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {clusters.map(cluster => (
            <div
              key={cluster.cluster_id}
              className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 cursor-pointer transition hover:shadow-lg ${
                activeCluster?.cluster_id === cluster.cluster_id
                  ? 'ring-2 ring-blue-500'
                  : ''
              }`}
              onClick={() => handleActivateCluster(cluster.cluster_id)}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-2xl">{PLUGIN_ICONS[cluster.plugin_type]}</span>
                {activeCluster?.cluster_id === cluster.cluster_id && (
                  <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded text-xs">Active</span>
                )}
              </div>
              <h4 className="font-semibold text-gray-900 dark:text-white">{cluster.name}</h4>
              <p className="text-sm text-gray-500">{cluster.region}</p>
              <p className="text-xs text-gray-400 mt-1">{cluster.plugin_type.toUpperCase()}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Add Plugin Modal */}
      {showAddPlugin && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">Add New Plugin</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Plugin Type
                </label>
                <select
                  value={newPlugin.type}
                  onChange={e => setNewPlugin({ ...newPlugin, type: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600"
                >
                  {availableTypes.map(t => (
                    <option key={t.type} value={t.type}>
                      {t.icon} {t.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Plugin Name
                </label>
                <input
                  type="text"
                  value={newPlugin.name}
                  onChange={e => setNewPlugin({ ...newPlugin, name: e.target.value })}
                  placeholder="My Plugin"
                  className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  AWS Regions (comma separated)
                </label>
                <input
                  type="text"
                  value={newPlugin.regions}
                  onChange={e => setNewPlugin({ ...newPlugin, regions: e.target.value })}
                  placeholder="ap-southeast-1, us-east-1"
                  className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowAddPlugin(false)}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleAddPlugin}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Add Plugin
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
