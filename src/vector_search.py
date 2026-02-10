"""
Vector Search Module for Operations Knowledge

Uses OpenSearch with Bedrock embeddings for semantic search.
"""

import json
import logging
from typing import Optional, Dict, Any, List
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

# OpenSearch Configuration
OPENSEARCH_ENDPOINT = "search-os2-pr7osiuyxyhawtfnyrwve6o2qe.ap-southeast-1.es.amazonaws.com"
KNOWLEDGE_INDEX = "aiops-knowledge"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024


class VectorKnowledgeSearch:
    """
    Vector-based semantic search for operations knowledge.
    
    Uses:
    - OpenSearch for vector storage and search
    - Bedrock Titan for embeddings
    """
    
    def __init__(self):
        self.endpoint = OPENSEARCH_ENDPOINT
        self.index = KNOWLEDGE_INDEX
        self.client = None
        self.bedrock = None
        self._initialized = False
        
        self._init_clients()
    
    def _init_clients(self):
        """Initialize OpenSearch and Bedrock clients."""
        try:
            from opensearchpy import OpenSearch, RequestsHttpConnection
            from requests_aws4auth import AWS4Auth
            import boto3
            
            # Get AWS credentials
            session = boto3.Session()
            credentials = session.get_credentials()
            region = session.region_name or 'ap-southeast-1'
            
            awsauth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                region,
                'es',
                session_token=credentials.token
            )
            
            # OpenSearch client
            self.client = OpenSearch(
                hosts=[{'host': self.endpoint, 'port': 443}],
                http_auth=awsauth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=30
            )
            
            # Bedrock client for embeddings
            self.bedrock = boto3.client('bedrock-runtime', region_name=region)
            
            self._initialized = True
            logger.info("Vector search clients initialized")
            
        except ImportError as e:
            logger.warning(f"Missing dependencies for vector search: {e}")
        except Exception as e:
            logger.warning(f"Failed to initialize vector search: {e}")
    
    def create_index(self) -> bool:
        """Create the knowledge index with vector mapping."""
        if not self.client:
            return False
        
        try:
            # Check if index exists
            if self.client.indices.exists(index=self.index):
                logger.info(f"Index {self.index} already exists")
                return True
            
            # Create index with kNN mapping
            mapping = {
                "settings": {
                    "index": {
                        "knn": True,
                        "number_of_shards": 3,
                        "number_of_replicas": 1
                    }
                },
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "title": {"type": "text", "analyzer": "standard"},
                        "description": {"type": "text", "analyzer": "standard"},
                        "content": {"type": "text", "analyzer": "standard"},
                        "category": {"type": "keyword"},
                        "service": {"type": "keyword"},
                        "severity": {"type": "keyword"},
                        "tags": {"type": "keyword"},
                        "type": {"type": "keyword"},  # pattern, sop, runbook
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": EMBEDDING_DIMENSION,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib"
                            }
                        }
                    }
                }
            }
            
            self.client.indices.create(index=self.index, body=mapping)
            logger.info(f"Created index: {self.index}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            return False
    
    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding using Bedrock Titan."""
        if not self.bedrock:
            return None
        
        try:
            # Truncate text if too long
            text = text[:8000]
            
            response = self.bedrock.invoke_model(
                modelId=EMBEDDING_MODEL,
                body=json.dumps({
                    "inputText": text,
                    "dimensions": EMBEDDING_DIMENSION,
                    "normalize": True
                })
            )
            
            result = json.loads(response['body'].read())
            return result.get('embedding')
            
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None
    
    def index_knowledge(
        self,
        doc_id: str,
        title: str,
        description: str,
        content: str,
        doc_type: str,
        category: str = "",
        service: str = "",
        severity: str = "",
        tags: List[str] = None
    ) -> bool:
        """Index a knowledge document with embeddings."""
        if not self._initialized:
            return False
        
        try:
            # Generate embedding from combined text
            combined_text = f"{title}\n{description}\n{content}"
            embedding = self._generate_embedding(combined_text)
            
            if not embedding:
                logger.warning(f"No embedding generated for {doc_id}")
                return False
            
            # Prepare document
            doc = {
                "id": doc_id,
                "title": title,
                "description": description,
                "content": content,
                "type": doc_type,
                "category": category,
                "service": service,
                "severity": severity,
                "tags": tags or [],
                "embedding": embedding,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Index document
            self.client.index(
                index=self.index,
                id=doc_id,
                body=doc,
                refresh=True
            )
            
            logger.info(f"Indexed document: {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to index document: {e}")
            return False
    
    def semantic_search(
        self,
        query: str,
        doc_type: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Semantic search using vector similarity.
        
        Args:
            query: Search query text
            doc_type: Filter by document type (pattern, sop, runbook)
            service: Filter by service
            limit: Max results to return
            
        Returns:
            List of matching documents with scores
        """
        if not self._initialized:
            return []
        
        try:
            # Generate query embedding
            query_embedding = self._generate_embedding(query)
            if not query_embedding:
                return []
            
            # Build query with filters
            must_clauses = []
            if doc_type:
                must_clauses.append({"term": {"type": doc_type}})
            if service:
                must_clauses.append({"term": {"service": service}})
            
            # kNN query
            query_body = {
                "size": limit,
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "should": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit
                                    }
                                }
                            }
                        ]
                    }
                }
            }
            
            # If no filters, use simple kNN
            if not must_clauses:
                query_body = {
                    "size": limit,
                    "query": {
                        "knn": {
                            "embedding": {
                                "vector": query_embedding,
                                "k": limit
                            }
                        }
                    }
                }
            
            # Execute search
            response = self.client.search(
                index=self.index,
                body=query_body
            )
            
            # Extract results
            results = []
            for hit in response['hits']['hits']:
                source = hit['_source']
                results.append({
                    "id": source.get('id'),
                    "title": source.get('title'),
                    "description": source.get('description'),
                    "type": source.get('type'),
                    "service": source.get('service'),
                    "category": source.get('category'),
                    "score": hit.get('_score', 0)
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
    
    def hybrid_search(
        self,
        query: str,
        doc_type: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining keyword and vector similarity.
        """
        if not self._initialized:
            return []
        
        try:
            query_embedding = self._generate_embedding(query)
            if not query_embedding:
                return []
            
            # Build hybrid query
            query_body = {
                "size": limit,
                "query": {
                    "bool": {
                        "should": [
                            # Keyword match
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title^3", "description^2", "content", "tags"],
                                    "boost": 0.3
                                }
                            },
                            # Vector similarity
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit * 2
                                    }
                                }
                            }
                        ],
                        "filter": []
                    }
                }
            }
            
            # Add filters
            if doc_type:
                query_body["query"]["bool"]["filter"].append({"term": {"type": doc_type}})
            if service:
                query_body["query"]["bool"]["filter"].append({"term": {"service": service}})
            
            response = self.client.search(index=self.index, body=query_body)
            
            results = []
            for hit in response['hits']['hits']:
                source = hit['_source']
                results.append({
                    "id": source.get('id'),
                    "title": source.get('title'),
                    "description": source.get('description'),
                    "type": source.get('type'),
                    "service": source.get('service'),
                    "score": hit.get('_score', 0)
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        if not self._initialized:
            return {"error": "Not initialized"}
        
        try:
            stats = self.client.indices.stats(index=self.index)
            count = self.client.count(index=self.index)
            
            return {
                "index": self.index,
                "document_count": count['count'],
                "size_bytes": stats['indices'][self.index]['total']['store']['size_in_bytes'],
                "status": "healthy"
            }
        except Exception as e:
            return {"error": str(e)}


# Singleton instance
_vector_search: Optional[VectorKnowledgeSearch] = None


def get_vector_search() -> VectorKnowledgeSearch:
    """Get or create vector search instance."""
    global _vector_search
    if _vector_search is None:
        _vector_search = VectorKnowledgeSearch()
    return _vector_search
