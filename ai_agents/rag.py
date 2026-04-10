"""RAG pipeline — retrieval-augmented generation for AI agents."""
import logging
import hashlib
import json
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class RAGStore:
    """Simple in-DB RAG store using TF-IDF and cosine similarity."""

    def __init__(self):
        self._vocabulary = {}
        self._documents = []
        self._vectors = None
        self._loaded = False

    def index_historical_data(self, force_refresh=False):
        """Index historical analyses, signals, and strategies for retrieval."""
        if self._loaded and not force_refresh:
            return

        self._documents = []

        # Index agent task results
        try:
            from ai_agents.models import AgentTask
            tasks = AgentTask.objects.filter(success=True).order_by('-created_at')[:500]
            for task in tasks:
                text = f"{task.agent}: {task.response_summary}"
                self._documents.append({
                    'id': f'agent_task_{task.id}',
                    'type': 'agent_analysis',
                    'text': text,
                    'metadata': {'agent': task.agent, 'date': str(task.created_at)},
                })
        except Exception as e:
            logger.debug(f"RAG: skipping agent tasks: {e}")

        # Index signal descriptions
        try:
            from signals.models import Signal
            signals = Signal.objects.order_by('-created_at')[:300]
            for sig in signals:
                text = f"{sig.instrument.symbol} {sig.signal_type} {sig.direction}: {sig.title}. {sig.description}"
                self._documents.append({
                    'id': f'signal_{sig.id}',
                    'type': 'signal',
                    'text': text,
                    'metadata': {'symbol': sig.instrument.symbol, 'score': sig.score},
                })
        except Exception as e:
            logger.debug(f"RAG: skipping signals: {e}")

        # Index news articles
        try:
            from scraping.models import NewsArticle
            articles = NewsArticle.objects.filter(ai_processed_at__isnull=False).order_by('-published_at')[:200]
            for art in articles:
                text = f"{art.title}. {art.ai_summary or art.content_summary or ''}"
                self._documents.append({
                    'id': f'news_{art.id}',
                    'type': 'news',
                    'text': text,
                    'metadata': {'source': art.source, 'sentiment': art.ai_sentiment_score},
                })
        except Exception as e:
            logger.debug(f"RAG: skipping news: {e}")

        # Index strategy results
        try:
            from strategies.models import Strategy
            strategies = Strategy.objects.order_by('-created_at')[:100]
            for strat in strategies:
                text = f"Strategy: {strat.name}. {strat.description}. Status: {strat.status}. P&L: {strat.pnl_pct}%"
                self._documents.append({
                    'id': f'strategy_{strat.id}',
                    'type': 'strategy',
                    'text': text,
                    'metadata': {'status': strat.status, 'pnl_pct': strat.pnl_pct},
                })
        except Exception as e:
            logger.debug(f"RAG: skipping strategies: {e}")

        # Build TF-IDF vectors
        self._build_tfidf()
        self._loaded = True
        logger.info(f"RAG: indexed {len(self._documents)} documents")

    def retrieve(self, query, top_k=5, doc_types=None):
        """Retrieve most relevant documents for a query.

        Args:
            query: search string
            top_k: number of results
            doc_types: filter by type (e.g., ['signal', 'news'])

        Returns list of {id, type, text, score, metadata}
        """
        self.index_historical_data()

        if not self._documents:
            return []

        query_vec = self._text_to_vector(query)
        if query_vec is None:
            return []

        # Compute cosine similarity
        similarities = []
        for i, doc in enumerate(self._documents):
            if doc_types and doc['type'] not in doc_types:
                continue

            if self._vectors is not None and i < len(self._vectors):
                doc_vec = self._vectors[i]
                sim = self._cosine_similarity(query_vec, doc_vec)
                similarities.append((i, sim))

        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in similarities[:top_k]:
            doc = self._documents[idx]
            results.append({
                'id': doc['id'],
                'type': doc['type'],
                'text': doc['text'][:500],
                'score': round(score, 4),
                'metadata': doc.get('metadata', {}),
            })

        return results

    def get_context_for_agent(self, agent_name, query, max_tokens=2000):
        """Get RAG context formatted for an agent prompt."""
        results = self.retrieve(query, top_k=8)
        if not results:
            return ""

        context_parts = ["RELEVANT HISTORICAL CONTEXT:"]
        char_count = 0

        for r in results:
            text = f"- [{r['type']}] {r['text']}"
            if char_count + len(text) > max_tokens * 4:  # rough char-to-token
                break
            context_parts.append(text)
            char_count += len(text)

        return "\n".join(context_parts)

    def _build_tfidf(self):
        """Build simple TF-IDF vectors."""
        # Build vocabulary
        word_counts = defaultdict(int)
        doc_word_counts = []

        for doc in self._documents:
            words = self._tokenize(doc['text'])
            wc = defaultdict(int)
            for w in words:
                wc[w] += 1
                word_counts[w] += 1
            doc_word_counts.append(wc)

        # Filter to top 5000 words
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:5000]
        self._vocabulary = {word: idx for idx, (word, _) in enumerate(sorted_words)}

        # Build vectors
        n_docs = len(self._documents)
        n_vocab = len(self._vocabulary)

        if n_vocab == 0:
            self._vectors = None
            return

        self._vectors = np.zeros((n_docs, n_vocab))

        # Document frequency
        df = np.zeros(n_vocab)
        for wc in doc_word_counts:
            for word in wc:
                if word in self._vocabulary:
                    df[self._vocabulary[word]] += 1

        # IDF
        idf = np.log((n_docs + 1) / (df + 1)) + 1

        # TF-IDF
        for i, wc in enumerate(doc_word_counts):
            for word, count in wc.items():
                if word in self._vocabulary:
                    idx = self._vocabulary[word]
                    self._vectors[i, idx] = count * idf[idx]

            # Normalize
            norm = np.linalg.norm(self._vectors[i])
            if norm > 0:
                self._vectors[i] /= norm

    def _text_to_vector(self, text):
        """Convert text to TF-IDF vector."""
        if not self._vocabulary:
            return None

        words = self._tokenize(text)
        vec = np.zeros(len(self._vocabulary))

        for word in words:
            if word in self._vocabulary:
                vec[self._vocabulary[word]] += 1

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    @staticmethod
    def _tokenize(text):
        """Simple word tokenization."""
        import re
        return re.findall(r'[a-zA-Z0-9]+', text.lower())

    @staticmethod
    def _cosine_similarity(a, b):
        """Cosine similarity between two vectors."""
        dot = np.dot(a, b)
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0
        return float(dot / (na * nb))


# Global singleton
rag_store = RAGStore()
