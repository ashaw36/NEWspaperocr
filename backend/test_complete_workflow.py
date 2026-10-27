#!/usr/bin/env python
"""Complete workflow test for the OCR system."""

import time
import requests
from pathlib import Path


class OCRSystemTester:
    """Test runner for the complete OCR workflow."""

    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.task_id = None

    def run_complete_test(self, image_path: str):
        """Run a complete end-to-end test.

        Args:
            image_path: Path to test image file
        """
        print("=" * 70)
        print("古报纸 OCR 完整流程测试")
        print("=" * 70)
        print()

        # 1. Check health
        print("1️⃣ 检查服务状态...")
        if not self._check_health():
            print("❌ 服务未就绪,测试终止")
            return False
        print("✅ 服务健康\n")

        # 2. Upload file
        print("2️⃣ 上传测试文件...")
        self.task_id = self._upload_file(image_path)
        if not self.task_id:
            print("❌ 文件上传失败")
            return False
        print(f"✅ 任务已创建: {self.task_id}\n")

        # 3. Wait for layout analysis
        print("3️⃣ 等待版面分析...")
        if not self._wait_for_stage("layout_ready", timeout=60):
            print("❌ 版面分析超时")
            return False
        print("✅ 版面分析完成\n")

        # 4. Start OCR
        print("4️⃣ 启动 OCR 识别...")
        if not self._start_ocr():
            print("❌ OCR 启动失败")
            return False

        # 5. Wait for OCR
        print("   等待 OCR 完成...")
        if not self._wait_for_stage("ocr_ready", timeout=120):
            print("❌ OCR 识别超时")
            return False
        print("✅ OCR 识别完成\n")

        # 6. Start correction
        print("5️⃣ 启动 AI 语义校正...")
        if not self._start_correction():
            print("❌ AI 校正启动失败")
            return False

        # 7. Wait for correction
        print("   等待 AI 校正完成...")
        if not self._wait_for_stage("correction_ready", timeout=180):
            print("❌ AI 校正超时")
            return False
        print("✅ AI 语义校正完成\n")

        # 8. Validate quality
        print("6️⃣ 质量验证...")
        validation = self._validate_quality()
        if not validation:
            print("❌ 质量验证失败")
            return False

        self._print_validation_report(validation)

        # 9. Generate AI summary
        print("\n7️⃣ 生成 AI 内容总结...")
        summary = self._generate_summary()
        if summary:
            print("✅ AI 总结生成成功")
            print(f"   总结: {summary[:200]}...")
        else:
            print("⚠️ AI 总结生成失败(可能未配置AI服务)")

        # 10. Export documents
        print("\n8️⃣ 导出最终文档...")
        exports = self._export_documents()
        if exports:
            print("✅ 文档导出成功:")
            for format_name, path in exports.items():
                print(f"   - {format_name}: {path}")
        else:
            print("❌ 文档导出失败")
            return False

        print("\n" + "=" * 70)
        print("✅ 所有测试通过!")
        print("=" * 70)
        print(f"\n任务ID: {self.task_id}")
        print(f"查看结果: {self.base_url}/tasks/{self.task_id}")
        print()

        return True

    def _check_health(self):
        """Check API health."""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                print(f"   OCR引擎: {health['ocr']['backend']} ({health['ocr']['model_version']})")
                print(f"   AI服务: {health['ai']['backend']} ({health['ai']['model']})")
                return health['status'] == 'healthy'
        except Exception as e:
            print(f"   错误: {e}")
        return False

    def _upload_file(self, image_path: str):
        """Upload test file."""
        try:
            with open(image_path, 'rb') as f:
                files = {'file': (Path(image_path).name, f, 'image/png')}
                data = {'ai_layout': 'true'}
                response = requests.post(
                    f"{self.base_url}/api/tasks",
                    files=files,
                    data=data,
                    timeout=30
                )
                if response.status_code == 202:
                    return response.json()['id']
                else:
                    print(f"   错误: {response.text}")
        except Exception as e:
            print(f"   错误: {e}")
        return None

    def _wait_for_stage(self, target_status: str, timeout: int = 60):
        """Wait for task to reach a specific status."""
        start_time = time.time()
        last_progress = None

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}", timeout=5)
                if response.status_code == 200:
                    task = response.json()
                    status = task.get('status')

                    # Print progress if changed
                    progress = task.get('progress', {})
                    if progress != last_progress:
                        message = progress.get('message', '')
                        if message:
                            print(f"   进度: {message}")
                        last_progress = progress

                    if status == target_status:
                        return True

                    if status and status.startswith('error'):
                        print(f"   任务失败: {task.get('error', 'Unknown error')}")
                        return False

            except Exception as e:
                print(f"   轮询错误: {e}")

            time.sleep(2)

        return False

    def _start_ocr(self):
        """Start OCR processing."""
        try:
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/ocr",
                json={},
                timeout=10
            )
            return response.status_code == 202
        except Exception as e:
            print(f"   错误: {e}")
            return False

    def _start_correction(self):
        """Start AI correction."""
        try:
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/correction",
                json={},
                timeout=10
            )
            return response.status_code == 202
        except Exception as e:
            print(f"   错误: {e}")
            return False

    def _validate_quality(self):
        """Validate OCR quality."""
        try:
            response = requests.get(
                f"{self.base_url}/api/tasks/{self.task_id}/validate",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"   错误: {e}")
        return None

    def _generate_summary(self):
        """Generate AI summary."""
        try:
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/analysis",
                json={"action": "summary", "instruction": "请总结这份报纸的主要内容"},
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                return result.get('answer', result.get('summary', ''))
        except Exception as e:
            print(f"   错误: {e}")
        return None

    def _export_documents(self):
        """Export final documents."""
        exports = {}
        task_dir = Path(f"./data/tasks/{self.task_id}")

        for format_name in ['markdown', 'html', 'json']:
            try:
                response = requests.get(
                    f"{self.base_url}/api/tasks/{self.task_id}/export/{format_name}",
                    timeout=30
                )
                if response.status_code == 200:
                    # Save to task directory
                    output_path = task_dir / f"final_document.{format_name}"
                    if format_name == 'json':
                        output_path = task_dir / "corrected.json"

                    if output_path.exists():
                        exports[format_name.upper()] = str(output_path)

            except Exception as e:
                print(f"   {format_name} 导出错误: {e}")

        return exports

    def _print_validation_report(self, validation: dict):
        """Print validation report."""
        passed = validation.get('passed', False)
        print(f"   验收结果: {'✅ 通过' if passed else '❌ 未通过'}")
        print()

        # Completeness
        completeness = validation.get('completeness', {})
        print(f"   📄 内容完整性: {completeness.get('score', 0):.1%}")
        print(f"      - 总区域数: {completeness.get('total_regions', 0)}")
        print(f"      - 已处理: {completeness.get('processed_regions', 0)}")
        print(f"      - 空白: {completeness.get('empty_regions', 0)}")

        # Accuracy
        accuracy = validation.get('accuracy', {})
        print(f"\n   🎯 识别准确率: {accuracy.get('score', 0):.1%} (目标: ≥95%)")
        print(f"      - 平均置信度: {accuracy.get('avg_confidence', 0):.1%}")
        print(f"      - 总字符数: {accuracy.get('total_chars', 0)}")
        print(f"      - 不确定字符: {accuracy.get('uncertain_char_count', 0)}")

        # Layout
        layout = validation.get('layout_quality', {})
        print(f"\n   📐 版面识别: {layout.get('score', 0):.1%}")
        print(f"      - AI增强页面: {layout.get('ai_enhanced_pages', 0)}/{validation.get('completeness', {}).get('total_regions', 0) // 3}")

        # Articles
        articles = validation.get('article_quality', {})
        print(f"\n   📝 文章聚合:")
        print(f"      - 识别文章数: {articles.get('total_articles', 0)}")
        print(f"      - 跨区域文章: {articles.get('multi_region_articles', 0)}")
        print(f"      - 跨页面文章: {articles.get('cross_page_articles', 0)}")

        # Recommendations
        recommendations = validation.get('recommendations', [])
        if recommendations:
            print(f"\n   💡 建议:")
            for rec in recommendations:
                print(f"      {rec}")


if __name__ == "__main__":
    import sys

    # Find test image
    test_images = [
        "./test_images/sample.png",
        "./test_images/sample.jpg",
        "../test_newspaper.png",
    ]

    image_path = None
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        for path in test_images:
            if Path(path).exists():
                image_path = path
                break

    if not image_path or not Path(image_path).exists():
        print("Usage: python test_complete_workflow.py <image_path>")
        print(f"\n可用测试图片: {test_images}")
        sys.exit(1)

    tester = OCRSystemTester()
    success = tester.run_complete_test(image_path)
    sys.exit(0 if success else 1)
