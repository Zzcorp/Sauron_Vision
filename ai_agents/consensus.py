"""Multi-model consensus — run critical analyses through multiple providers."""
import logging
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Run the same prompt through multiple AI models and compare results."""

    def __init__(self, models=None):
        """
        Args:
            models: list of (provider_name, model_id) tuples.
                    Default: Claude + OpenAI if both keys configured.
        """
        self.models = models or self._detect_available_models()

    def _detect_available_models(self):
        """Detect which AI providers are configured."""
        import os
        models = []
        if os.getenv('ANTHROPIC_API_KEY'):
            models.append(('claude', 'claude-haiku-4-5-20251001'))
        if os.getenv('OPENAI_API_KEY'):
            models.append(('openai', 'gpt-4o-mini'))
        if not models:
            models = [('claude', 'claude-haiku-4-5-20251001')]
        return models

    def run(self, system_prompt, user_message, require_json=False):
        """Run prompt through all configured models and compare.

        Returns dict with:
            responses: list of {provider, model, response, latency_ms}
            consensus: bool — do all models agree?
            agreement_score: float 0-1
            summary: str — consensus summary or disagreement highlights
        """
        results = []

        def _call_model(provider_name, model_id):
            import time
            start = time.time()
            try:
                provider = self._get_provider(provider_name)
                text, usage = provider.complete(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    model=model_id,
                    agent_name="consensus",
                )
                latency = int((time.time() - start) * 1000)
                return {
                    'provider': provider_name,
                    'model': model_id,
                    'response': text,
                    'latency_ms': latency,
                    'usage': usage,
                    'success': True,
                }
            except Exception as e:
                return {
                    'provider': provider_name,
                    'model': model_id,
                    'response': None,
                    'error': str(e),
                    'success': False,
                }

        # Run in parallel
        with ThreadPoolExecutor(max_workers=len(self.models)) as executor:
            futures = {
                executor.submit(_call_model, prov, model): (prov, model)
                for prov, model in self.models
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Analyze agreement
        successful = [r for r in results if r['success']]

        if len(successful) < 2:
            return {
                'responses': results,
                'consensus': True if len(successful) == 1 else None,
                'agreement_score': 1.0 if successful else 0,
                'summary': successful[0]['response'] if successful else 'All models failed',
            }

        agreement = self._calculate_agreement(successful, require_json)

        return {
            'responses': results,
            'consensus': agreement['is_consensus'],
            'agreement_score': agreement['score'],
            'summary': agreement['summary'],
            'disagreements': agreement.get('disagreements', []),
        }

    def _calculate_agreement(self, responses, require_json):
        """Calculate how much models agree."""
        texts = [r['response'] for r in responses]

        if require_json:
            return self._json_agreement(responses)

        # Simple keyword overlap for text responses
        word_sets = []
        for text in texts:
            words = set(text.lower().split())
            word_sets.append(words)

        if len(word_sets) < 2:
            return {'is_consensus': True, 'score': 1.0, 'summary': texts[0]}

        # Jaccard similarity between all pairs
        similarities = []
        for i in range(len(word_sets)):
            for j in range(i + 1, len(word_sets)):
                intersection = word_sets[i] & word_sets[j]
                union = word_sets[i] | word_sets[j]
                sim = len(intersection) / len(union) if union else 0
                similarities.append(sim)

        avg_sim = sum(similarities) / len(similarities) if similarities else 0

        # Check for directional agreement (bullish/bearish/neutral)
        directions = []
        for text in texts:
            lower = text.lower()
            bull = sum(1 for w in ['buy', 'long', 'bullish', 'positive', 'upside'] if w in lower)
            bear = sum(1 for w in ['sell', 'short', 'bearish', 'negative', 'downside'] if w in lower)
            if bull > bear:
                directions.append('bullish')
            elif bear > bull:
                directions.append('bearish')
            else:
                directions.append('neutral')

        directional_consensus = len(set(directions)) == 1

        score = avg_sim * 0.4 + (1.0 if directional_consensus else 0.0) * 0.6

        disagreements = []
        if not directional_consensus:
            for i, r in enumerate(responses):
                disagreements.append({
                    'provider': r['provider'],
                    'direction': directions[i],
                })

        if directional_consensus:
            summary = texts[0]
        else:
            parts = [r['provider'] + '=' + d for r, d in zip(responses, directions)]
            summary = "Models disagree: " + ', '.join(parts)

        return {
            'is_consensus': score > 0.5 and directional_consensus,
            'score': round(score, 3),
            'summary': summary,
            'disagreements': disagreements,
        }

    def _json_agreement(self, responses):
        """Check agreement on JSON responses."""
        parsed = []
        for r in responses:
            try:
                text = r['response'].strip()
                if text.startswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                parsed.append(json.loads(text))
            except (json.JSONDecodeError, IndexError):
                parsed.append(None)

        valid = [(r, p) for r, p in zip(responses, parsed) if p is not None]
        if len(valid) < 2:
            return {'is_consensus': len(valid) == 1, 'score': 1.0 if valid else 0,
                    'summary': valid[0][0]['response'] if valid else 'Parse failed'}

        # Compare key fields
        all_keys = set()
        for _, p in valid:
            if isinstance(p, dict):
                all_keys.update(p.keys())

        matching_keys = 0
        total_keys = len(all_keys)
        for key in all_keys:
            values = [p.get(key) for _, p in valid if isinstance(p, dict)]
            if len(set(str(v) for v in values)) == 1:
                matching_keys += 1

        score = matching_keys / total_keys if total_keys > 0 else 0
        return {
            'is_consensus': score > 0.6,
            'score': round(score, 3),
            'summary': f"{matching_keys}/{total_keys} fields agree across models",
        }

    def _get_provider(self, name):
        """Get an AI provider instance."""
        if name == 'claude':
            from ai_agents.providers.claude_provider import ClaudeProvider
            return ClaudeProvider()
        elif name == 'openai':
            from ai_agents.providers.openai_provider import OpenAIProvider
            return OpenAIProvider()
        elif name == 'ollama':
            from ai_agents.providers.ollama_provider import OllamaProvider
            return OllamaProvider()
        raise ValueError(f"Unknown provider: {name}")
