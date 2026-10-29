"""Enhanced document composition for structured newspaper output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime


class DocumentComposer:
    """Compose structured, complete newspaper documents from OCR results."""

    def __init__(self):
        self.quality_threshold = 0.95

    def compose_markdown(self, task_data: Dict, pages: List[Dict]) -> str:
        """Generate a complete Markdown document from OCR results.

        Args:
            task_data: Task metadata
            pages: List of page results with regions and text

        Returns:
            Formatted Markdown document
        """
        lines = []
        lines.append(f"# {task_data.get('filename', '历史报纸')}")
        lines.append(f"\n> OCR识别时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> 总页数: {len(pages)}")
        lines.append(f"> 识别引擎: PaddleOCR + AI增强")
        lines.append("")

        # Group content by articles across all pages
        articles = self._extract_articles(pages)

        if articles:
            lines.append("## 📰 识别的文章")
            lines.append("")
            for idx, article in enumerate(articles, 1):
                lines.append(f"### {idx}. {article['title']}")
                lines.append("")
                if article.get("subtitle"):
                    lines.append(f"*{article['subtitle']}*")
                    lines.append("")
                lines.append(article["content"])
                lines.append("")
                lines.append(
                    f"*[置信度: {article['confidence']:.1%}, 页码: {', '.join(map(str, article['pages']))}]*"
                )
                lines.append("")
                lines.append("---")
                lines.append("")

        # Add page-by-page raw content
        lines.append("## 📄 按页面完整内容")
        lines.append("")
        for page in pages:
            lines.append(f"### 第 {page['page_number']} 页")
            lines.append("")

            # Page text
            page_text = page.get("corrected_text") or page.get("text", "")
            if page_text:
                lines.append(page_text)
            else:
                lines.append("*(本页无可识别文字)*")
            lines.append("")
            lines.append("---")
            lines.append("")

        # Quality metrics
        lines.append("## 📊 识别质量报告")
        lines.append("")
        metrics = self._calculate_quality(pages)
        lines.append(f"- **总字符数**: {metrics['total_chars']}")
        lines.append(f"- **平均置信度**: {metrics['avg_confidence']:.1%}")
        lines.append(
            f"- **高质量区域**: {metrics['high_quality_regions']}/{metrics['total_regions']} ({metrics['high_quality_ratio']:.1%})"
        )
        lines.append(f"- **待人工复核区域**: {metrics['low_quality_regions']}")
        lines.append("")

        return "\n".join(lines)

    def compose_html(self, task_data: Dict, pages: List[Dict]) -> str:
        """Generate a styled HTML document from OCR results."""
        articles = self._extract_articles(pages)
        metrics = self._calculate_quality(pages)

        html_parts = []
        html_parts.append(
            """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: "Songti SC", STSong, "华文宋体", serif;
            line-height: 1.8;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #fafafa;
            color: #2c3e50;
        }}
        .header {{
            border-bottom: 3px double #8b4513;
            padding-bottom: 20px;
            margin-bottom: 40px;
        }}
        h1 {{
            font-size: 2.5em;
            color: #8b4513;
            text-align: center;
            margin: 0;
        }}
        .metadata {{
            text-align: center;
            color: #666;
            margin-top: 10px;
        }}
        .article {{
            background: white;
            padding: 30px;
            margin: 30px 0;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .article-title {{
            font-size: 1.8em;
            color: #2c3e50;
            margin-bottom: 15px;
            border-left: 4px solid #8b4513;
            padding-left: 15px;
        }}
        .article-subtitle {{
            font-size: 1.2em;
            color: #7f8c8d;
            font-style: italic;
            margin-bottom: 20px;
        }}
        .article-content {{
            text-align: justify;
            line-height: 2;
            font-size: 1.1em;
        }}
        .article-meta {{
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px dashed #ddd;
            color: #95a5a6;
            font-size: 0.9em;
        }}
        .quality-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
        }}
        .quality-high {{ background: #d4edda; color: #155724; }}
        .quality-medium {{ background: #fff3cd; color: #856404; }}
        .quality-low {{ background: #f8d7da; color: #721c24; }}
        .metrics {{
            background: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }}
        .metrics h2 {{
            color: #34495e;
            margin-top: 0;
        }}
        .metrics ul {{
            list-style: none;
            padding: 0;
        }}
        .metrics li {{
            padding: 5px 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <div class="metadata">
            识别时间: {timestamp}<br>
            总页数: {page_count} | 识别引擎: PaddleOCR + AI增强
        </div>
    </div>
""".format(
                title=task_data.get("filename", "历史报纸"),
                timestamp=datetime.now().strftime("%Y年%m月%d日 %H:%M"),
                page_count=len(pages),
            )
        )

        # Articles section
        if articles:
            html_parts.append('<div class="section">')
            for idx, article in enumerate(articles, 1):
                conf = article["confidence"]
                quality_class = (
                    "quality-high"
                    if conf >= 0.9
                    else ("quality-medium" if conf >= 0.75 else "quality-low")
                )

                html_parts.append(f'<div class="article">')
                html_parts.append(
                    f'<div class="article-title">{idx}. {article["title"]}</div>'
                )
                if article.get("subtitle"):
                    html_parts.append(
                        f'<div class="article-subtitle">{article["subtitle"]}</div>'
                    )
                html_parts.append(
                    f'<div class="article-content">{article["content"].replace(chr(10), "<br>")}</div>'
                )
                html_parts.append(f'<div class="article-meta">')
                html_parts.append(
                    f'<span class="quality-badge {quality_class}">置信度 {conf:.1%}</span> '
                )
                html_parts.append(f'页码: {", ".join(map(str, article["pages"]))}')
                html_parts.append(f"</div>")
                html_parts.append("</div>")
            html_parts.append("</div>")

        # Quality metrics
        html_parts.append('<div class="metrics">')
        html_parts.append("<h2>📊 识别质量报告</h2>")
        html_parts.append("<ul>")
        html_parts.append(
            f'<li><strong>总字符数:</strong> {metrics["total_chars"]}</li>'
        )
        html_parts.append(
            f'<li><strong>平均置信度:</strong> {metrics["avg_confidence"]:.1%}</li>'
        )
        html_parts.append(
            f'<li><strong>高质量区域:</strong> {metrics["high_quality_regions"]}/{metrics["total_regions"]} ({metrics["high_quality_ratio"]:.1%})</li>'
        )
        html_parts.append(
            f'<li><strong>待复核区域:</strong> {metrics["low_quality_regions"]}</li>'
        )
        html_parts.append("</ul>")
        html_parts.append("</div>")

        html_parts.append("</body></html>")
        return "".join(html_parts)

    def _extract_articles(self, pages: List[Dict]) -> List[Dict]:
        """Extract and group articles from pages."""
        # Collect all article groups
        article_map = {}

        for page in pages:
            page_num = page.get("page_number", 0)
            regions = page.get("regions", [])

            for region in regions:
                article_id = region.get("article_id", f"page-{page_num}-unknown")
                text = region.get("corrected_text") or region.get("raw_text", "")
                label = region.get("label", "body")
                conf = region.get("confidence", 0.0)

                if article_id not in article_map:
                    article_map[article_id] = {
                        "title": "",
                        "subtitle": "",
                        "content": "",
                        "pages": set(),
                        "confidences": [],
                        "region_count": 0,
                    }

                article = article_map[article_id]
                article["pages"].add(page_num)
                article["confidences"].append(conf)
                article["region_count"] += 1

                if label == "title" and not article["title"]:
                    article["title"] = text.strip()
                elif label == "subtitle" and not article["subtitle"]:
                    article["subtitle"] = text.strip()
                elif label in ("body", "text"):
                    if article["content"]:
                        article["content"] += "\n"
                    article["content"] += text.strip()

        # Convert to list and enrich
        articles = []
        for article_id, data in article_map.items():
            if not data["content"]:  # Skip articles with no body content
                continue

            # Generate title if missing
            if not data["title"]:
                content_preview = data["content"][:30].replace("\n", " ")
                data["title"] = f"{content_preview}..."

            # Calculate average confidence
            avg_conf = (
                sum(data["confidences"]) / len(data["confidences"])
                if data["confidences"]
                else 0.0
            )

            articles.append(
                {
                    "article_id": article_id,
                    "title": data["title"],
                    "subtitle": data["subtitle"],
                    "content": data["content"],
                    "pages": sorted(data["pages"]),
                    "confidence": avg_conf,
                    "region_count": data["region_count"],
                }
            )

        # Sort by first page appearance
        articles.sort(key=lambda a: (min(a["pages"]), a["article_id"]))
        return articles

    def _calculate_quality(self, pages: List[Dict]) -> Dict:
        """Calculate quality metrics for the OCR results."""
        total_chars = 0
        total_regions = 0
        high_quality_regions = 0
        low_quality_regions = 0
        confidence_sum = 0.0
        confidence_count = 0

        for page in pages:
            regions = page.get("regions", [])
            total_regions += len(regions)

            for region in regions:
                text = region.get("corrected_text") or region.get("raw_text", "")
                total_chars += len(text)

                conf = region.get("confidence", 0.0)
                if conf > 0:
                    confidence_sum += conf
                    confidence_count += 1

                    if conf >= self.quality_threshold:
                        high_quality_regions += 1
                    elif conf < 0.75:
                        low_quality_regions += 1

        avg_confidence = (
            confidence_sum / confidence_count if confidence_count > 0 else 0.0
        )
        high_quality_ratio = (
            high_quality_regions / total_regions if total_regions > 0 else 0.0
        )

        return {
            "total_chars": total_chars,
            "total_regions": total_regions,
            "high_quality_regions": high_quality_regions,
            "low_quality_regions": low_quality_regions,
            "avg_confidence": avg_confidence,
            "high_quality_ratio": high_quality_ratio,
        }
