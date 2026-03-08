import { useState, useEffect } from 'react';

const PLUGIN_ICONS = {
  eks: '☸️',
  ec2: '🖥️',
  lambda: 'λ',
  hpc: '🖧'
};

export default function ClusterSelector({ onClusterChange }) {
  const [clusters, setClusters] = useState([]);
  const [activeCluster, setActiveCluster] = useState(null);
  const [isOpen, setIsOpen] = useState(false);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchClusters();
    const interval = setInterval(fetchClusters, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  const fetchClusters = async () => {
    try {
      const res = await fetch(`${API_URL}/api/clusters`);
      const data = await res.json();
      setClusters(data.clusters || []);
      setActiveCluster(data.active_cluster);
    } catch (error) {
      console.error('Failed to fetch clusters:', error);
    }
  };

  const handleSelectCluster = async (cluster) => {
    try {
      await fetch(`${API_URL}/api/clusters/${cluster.cluster_id}/activate`, { 
        method: 'POST' 
      });
      setActiveCluster(cluster);
      setIsOpen(false);
      if (onClusterChange) {
        onClusterChange(cluster);
      }
    } catch (error) {
      console.error('Failed to activate cluster:', error);
    }
  };

  // Group clusters by type
  const groupedClusters = clusters.reduce((acc, cluster) => {
    if (!acc[cluster.plugin_type]) {
      acc[cluster.plugin_type] = [];
    }
    acc[cluster.plugin_type].push(cluster);
    return acc;
  }, {});

  return (
    <div className="relative">
      {/* Current Cluster Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition"
      >
        {activeCluster ? (
          <>
            <span className="text-lg">{PLUGIN_ICONS[activeCluster.plugin_type]}</span>
            <div className="text-left">
              <p className="font-medium text-gray-900 dark:text-white text-sm">{activeCluster.name}</p>
              <p className="text-xs text-gray-500">{activeCluster.region}</p>
            </div>
          </>
        ) : (
          <span className="text-gray-500">Select Cluster</span>
        )}
        <svg className={`w-4 h-4 ml-2 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-72 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 max-h-96 overflow-auto">
          {Object.entries(groupedClusters).map(([type, typeClusters]) => (
            <div key={type}>
              <div className="px-4 py-2 bg-gray-50 dark:bg-gray-700 border-b border-gray-200 dark:border-gray-600">
                <span className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                  {PLUGIN_ICONS[type]} {type.toUpperCase()}
                </span>
              </div>
              {typeClusters.map(cluster => (
                <button
                  key={cluster.cluster_id}
                  onClick={() => handleSelectCluster(cluster)}
                  className={`w-full px-4 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-between ${
                    activeCluster?.cluster_id === cluster.cluster_id ? 'bg-blue-50 dark:bg-blue-900' : ''
                  }`}
                >
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">{cluster.name}</p>
                    <p className="text-xs text-gray-500">{cluster.region}</p>
                  </div>
                  {activeCluster?.cluster_id === cluster.cluster_id && (
                    <span className="text-blue-500">✓</span>
                  )}
                </button>
              ))}
            </div>
          ))}
          
          {clusters.length === 0 && (
            <div className="px-4 py-8 text-center text-gray-500">
              <p>No clusters available</p>
              <p className="text-xs mt-1">Add plugins to discover clusters</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
