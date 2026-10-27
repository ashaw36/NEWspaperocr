"""Quality validation and completeness verification for OCR results."""

from __future__ import annotations

from typing import Dict, List, Tuple


class QualityValidator:
    """Validate OCR quality and completeness."""

    def __init__(self, target_accuracy: float = 0.95):
        self.target_accuracy = target_accuracy

    def validate_task(self, task_data: Dict) -> Dict:
        """Comprehensive validation of a completed OCR task.

        Args:
            task_data: Complete task data with OCR results

        Returns:
            Validation report with pass/fail status and details
        """
        pages = task_data.get('pages', [])

        # Calculate metrics
        completeness = self._check_completeness(pages)
        accuracy = self._estimate_accuracy(pages)
        layout_quality = self._check_layout_quality(pages)
        article_quality = self._check_article_aggregation(pages)

        # Determine pass/fail
        passed = (
            completeness['score'] >= 0.95 and
            accuracy['score'] >= self.target_accuracy and
            layout_quality['score'] >= 0.90
        )

        return {
            'passed': passed,
            'target_accuracy': self.target_accuracy,
            'completeness': completeness,
            'accuracy': accuracy,
            'layout_quality': layout_quality,
            'article_quality': article_quality,
            'recommendations': self._generate_recommendations(
                completeness, accuracy, layout_quality, article_quality
            )
        }

    def _check_completeness(self, pages: List[Dict]) -> Dict:
        """Verify all content has been recognized."""
        total_regions = 0
        processed_regions = 0
        empty_regions = 0

        for page in pages:
            regions = page.get('regions', [])
            total_regions += len(regions)

            for region in regions:
                if region.get('label') == 'ignore':
                    continue

                text = region.get('corrected_text') or region.get('raw_text', '')
                if text.strip():
                    processed_regions += 1
                else:
                    empty_regions += 1

        score = processed_regions / total_regions if total_regions > 0 else 0.0

        return {
            'score': score,
            'total_regions': total_regions,
            'processed_regions': processed_regions,
            'empty_regions': empty_regions,
            'status': 'pass' if score >= 0.95 else 'warning' if score >= 0.85 else 'fail'
        }

    def _estimate_accuracy(self, pages: List[Dict]) -> Dict:
        """Estimate recognition accuracy from confidence scores and quality indicators."""
        confidence_scores = []
        char_count = 0
        uncertain_char_count = 0
        low_confidence_regions = []

        for page in pages:
            regions = page.get('regions', [])

            for region in regions:
                if region.get('label') == 'ignore':
                    continue

                conf = region.get('confidence', 0.0)
                if conf > 0:
                    confidence_scores.append(conf)

                text = region.get('corrected_text') or region.get('raw_text', '')
                char_count += len(text)
                uncertain_char_count += text.count('□')  # Placeholder for unreadable chars

                if conf < 0.75 and text.strip():
                    low_confidence_regions.append({
                        'page': page.get('page_number'),
                        'region_id': region.get('region_id'),
                        'confidence': conf,
                        'text_preview': text[:50]
                    })

        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
        uncertain_ratio = uncertain_char_count / char_count if char_count > 0 else 0.0

        # Adjust score based on uncertainty markers
        estimated_accuracy = avg_confidence * (1 - uncertain_ratio)

        return {
            'score': estimated_accuracy,
            'avg_confidence': avg_confidence,
            'uncertain_char_count': uncertain_char_count,
            'uncertain_ratio': uncertain_ratio,
            'total_chars': char_count,
            'low_confidence_regions': low_confidence_regions[:10],  # Top 10 problem areas
            'status': 'pass' if estimated_accuracy >= self.target_accuracy else 'fail'
        }

    def _check_layout_quality(self, pages: List[Dict]) -> Dict:
        """Check layout recognition quality."""
        total_pages = len(pages)
        ai_enhanced_pages = 0
        layout_warnings = []

        for page in pages:
            layout = page.get('layout', {})
            if layout.get('source') in ('ai+computer-vision', 'user-reviewed'):
                ai_enhanced_pages += 1

            # Check for layout issues
            regions = page.get('regions', [])
            if not regions:
                layout_warnings.append({
                    'page': page.get('page_number'),
                    'issue': 'No regions detected'
                })
            elif len(regions) == 1 and regions[0].get('label') != 'masthead':
                layout_warnings.append({
                    'page': page.get('page_number'),
                    'issue': 'Only one region detected (possible layout detection failure)'
                })

        ai_ratio = ai_enhanced_pages / total_pages if total_pages > 0 else 0.0
        score = 1.0 - (len(layout_warnings) / total_pages if total_pages > 0 else 1.0)

        return {
            'score': score,
            'ai_enhanced_pages': ai_enhanced_pages,
            'ai_enhancement_ratio': ai_ratio,
            'warnings': layout_warnings,
            'status': 'pass' if score >= 0.90 else 'warning' if score >= 0.75 else 'fail'
        }

    def _check_article_aggregation(self, pages: List[Dict]) -> Dict:
        """Verify article boundary detection and aggregation."""
        article_ids = set()
        multi_region_articles = 0
        cross_page_articles = set()

        article_page_map = {}

        for page in pages:
            regions = page.get('regions', [])
            page_num = page.get('page_number')

            for region in regions:
                article_id = region.get('article_id')
                if not article_id or region.get('label') == 'ignore':
                    continue

                article_ids.add(article_id)

                if article_id not in article_page_map:
                    article_page_map[article_id] = {
                        'pages': set(),
                        'region_count': 0
                    }

                article_page_map[article_id]['pages'].add(page_num)
                article_page_map[article_id]['region_count'] += 1

        for article_id, data in article_page_map.items():
            if data['region_count'] > 1:
                multi_region_articles += 1
            if len(data['pages']) > 1:
                cross_page_articles.add(article_id)

        multi_region_ratio = multi_region_articles / len(article_ids) if article_ids else 0.0

        return {
            'total_articles': len(article_ids),
            'multi_region_articles': multi_region_articles,
            'cross_page_articles': len(cross_page_articles),
            'multi_region_ratio': multi_region_ratio,
            'notes': [
                f'识别出 {len(article_ids)} 篇文章',
                f'{multi_region_articles} 篇文章跨多个区域',
                f'{len(cross_page_articles)} 篇文章跨多个页面'
            ]
        }

    def _generate_recommendations(
        self,
        completeness: Dict,
        accuracy: Dict,
        layout: Dict,
        articles: Dict
    ) -> List[str]:
        """Generate actionable recommendations based on validation results."""
        recommendations = []

        if completeness['status'] != 'pass':
            recommendations.append(
                f"⚠️ 内容完整性: {completeness['empty_regions']} 个区域未识别到文字,请检查原图质量或调整识别参数"
            )

        if accuracy['status'] != 'pass':
            recommendations.append(
                f"⚠️ 识别准确率: 估计准确率 {accuracy['score']:.1%} 低于目标 {accuracy.get('target', 0.95):.1%}"
            )

            if accuracy['uncertain_char_count'] > 0:
                recommendations.append(
                    f"   发现 {accuracy['uncertain_char_count']} 个不确定字符(□),建议人工复核"
                )

            if accuracy['low_confidence_regions']:
                recommendations.append(
                    f"   {len(accuracy['low_confidence_regions'])} 个区域置信度较低,建议重点复核"
                )

        if layout['status'] != 'pass':
            recommendations.append(
                f"⚠️ 版面识别: {len(layout['warnings'])} 个页面存在版面识别问题"
            )

        if not recommendations:
            recommendations.append("✅ 所有验收标准均已达成,识别质量良好")

        return recommendations
