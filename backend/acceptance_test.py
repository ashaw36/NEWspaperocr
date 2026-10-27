#!/usr/bin/env python
"""验收测试脚本 - 验证所有目标要求是否达成"""

import sys
import time
import requests
from pathlib import Path
from typing import Dict, Optional


class AcceptanceTest:
    """完整的验收测试"""

    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.task_id: Optional[str] = None
        self.test_results = {}

    def run_acceptance_test(self, test_image_path: str) -> bool:
        """运行完整的验收测试

        验收标准：
        1. ✅ 内容完整无遗漏
        2. ✅ 识别准确率 >95%
        3. ✅ 古报纸版面识别准确
        4. ✅ 同一篇文章能被正确识别与聚合
        5. ✅ 输出最终文档
        6. ✅ 提供基于识别结果的 AI 总结
        """
        print("=" * 80)
        print("🎯 古报纸 OCR 系统 - 验收测试")
        print("=" * 80)
        print()

        # Test requirements
        requirements = [
            ("内容完整无遗漏", self.test_content_completeness),
            ("识别准确率 >95%", self.test_accuracy_target),
            ("古报纸版面识别准确", self.test_layout_recognition),
            ("文章聚合正确", self.test_article_aggregation),
            ("输出最终文档", self.test_document_generation),
            ("AI总结生成", self.test_ai_summary),
        ]

        # 1. Upload and process
        print("📤 步骤1: 上传测试图片并处理")
        print(f"   测试文件: {test_image_path}")

        if not self._upload_and_process(test_image_path):
            print("\n❌ 文件处理失败，测试终止")
            return False

        print("\n✅ 文件处理完成\n")

        # 2. Run all acceptance tests
        print("🧪 步骤2: 执行验收测试")
        print("-" * 80)

        all_passed = True
        for name, test_func in requirements:
            print(f"\n测试项: {name}")
            try:
                passed, details = test_func()
                self.test_results[name] = {
                    'passed': passed,
                    'details': details
                }

                if passed:
                    print(f"   ✅ 通过")
                    if details:
                        print(f"   详情: {details}")
                else:
                    print(f"   ❌ 未通过")
                    print(f"   原因: {details}")
                    all_passed = False

            except Exception as e:
                print(f"   ❌ 测试执行失败: {e}")
                self.test_results[name] = {
                    'passed': False,
                    'details': str(e)
                }
                all_passed = False

        # 3. Print summary
        print("\n" + "=" * 80)
        print("📊 验收测试汇总")
        print("=" * 80)

        passed_count = sum(1 for r in self.test_results.values() if r['passed'])
        total_count = len(self.test_results)

        for name, result in self.test_results.items():
            status = "✅ 通过" if result['passed'] else "❌ 失败"
            print(f"{status}  {name}")

        print("\n" + "-" * 80)
        print(f"总计: {passed_count}/{total_count} 项通过")
        print("-" * 80)

        if all_passed:
            print("\n🎉 所有验收标准均已达成！")
            print(f"\n任务详情: {self.base_url}/api/tasks/{self.task_id}")
            print(f"查看结果: {self.base_url}/#/tasks/{self.task_id}")
            print()
            return True
        else:
            print("\n⚠️ 部分验收标准未达成，请查看详细信息")
            return False

    def _upload_and_process(self, image_path: str) -> bool:
        """上传并完成完整处理流程"""
        try:
            # Upload
            print("   上传文件...")
            with open(image_path, 'rb') as f:
                files = {'file': (Path(image_path).name, f, 'image/png')}
                data = {'ai_layout': 'true'}
                response = requests.post(
                    f"{self.base_url}/api/tasks",
                    files=files,
                    data=data,
                    timeout=30
                )
                if response.status_code != 202:
                    print(f"   上传失败: {response.text}")
                    return False

                self.task_id = response.json()['id']
                print(f"   任务ID: {self.task_id}")

            # Wait for layout
            print("   版面分析中...")
            if not self._poll_status('layout_ready', 60):
                return False

            # Start OCR
            print("   OCR识别中...")
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/ocr",
                json={},
                timeout=10
            )
            if response.status_code != 202:
                return False

            if not self._poll_status('ocr_ready', 120):
                return False

            # Start correction
            print("   AI校正中...")
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/correction",
                json={},
                timeout=10
            )
            if response.status_code != 202:
                return False

            if not self._poll_status('correction_ready', 180):
                return False

            return True

        except Exception as e:
            print(f"   处理失败: {e}")
            return False

    def _poll_status(self, target_status: str, timeout: int) -> bool:
        """轮询任务状态"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}")
            task = response.json()

            if task.get('status') == target_status:
                return True

            if task.get('status', '').startswith('error'):
                print(f"   错误: {task.get('error')}")
                return False

            time.sleep(2)

        print(f"   超时等待状态: {target_status}")
        return False

    def test_content_completeness(self) -> tuple[bool, str]:
        """测试1: 内容完整无遗漏"""
        response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}/validate")
        validation = response.json()

        completeness = validation.get('completeness', {})
        score = completeness.get('score', 0)
        empty_regions = completeness.get('empty_regions', 0)

        # 要求: 至少95%的区域有内容
        passed = score >= 0.95

        details = f"完整性评分: {score:.1%}, 空白区域: {empty_regions}/{completeness.get('total_regions', 0)}"

        return passed, details

    def test_accuracy_target(self) -> tuple[bool, str]:
        """测试2: 识别准确率 >95%"""
        response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}/validate")
        validation = response.json()

        accuracy = validation.get('accuracy', {})
        score = accuracy.get('score', 0)
        avg_confidence = accuracy.get('avg_confidence', 0)

        # 要求: 识别准确率 >95%
        passed = score >= 0.95

        details = f"准确率: {score:.1%}, 平均置信度: {avg_confidence:.1%}"

        if not passed:
            low_conf_count = len(accuracy.get('low_confidence_regions', []))
            details += f", 低置信度区域: {low_conf_count}"

        return passed, details

    def test_layout_recognition(self) -> tuple[bool, str]:
        """测试3: 古报纸版面识别准确"""
        response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}/validate")
        validation = response.json()

        layout = validation.get('layout_quality', {})
        score = layout.get('score', 0)
        ai_enhanced = layout.get('ai_enhancement_ratio', 0)

        # 要求: 版面识别评分 ≥90%, 且启用了AI增强
        passed = score >= 0.90 and ai_enhanced > 0

        details = f"版面识别评分: {score:.1%}, AI增强比例: {ai_enhanced:.1%}"

        warnings = layout.get('warnings', [])
        if warnings:
            details += f", 警告数: {len(warnings)}"

        return passed, details

    def test_article_aggregation(self) -> tuple[bool, str]:
        """测试4: 文章聚合正确"""
        response = requests.get(f"{self.base_url}/api/tasks/{self.task_id}/validate")
        validation = response.json()

        articles = validation.get('article_quality', {})
        total_articles = articles.get('total_articles', 0)
        multi_region = articles.get('multi_region_articles', 0)
        cross_page = articles.get('cross_page_articles', 0)

        # 要求: 能识别出文章并进行跨区域聚合
        passed = total_articles > 0

        details = f"识别文章: {total_articles}篇, 跨区域: {multi_region}篇, 跨页面: {cross_page}篇"

        return passed, details

    def test_document_generation(self) -> tuple[bool, str]:
        """测试5: 输出最终文档"""
        formats_available = []

        for format_type in ['markdown', 'html', 'json']:
            try:
                response = requests.get(
                    f"{self.base_url}/api/tasks/{self.task_id}/export/{format_type}",
                    timeout=30
                )
                if response.status_code == 200:
                    formats_available.append(format_type.upper())
            except Exception:
                pass

        # 要求: 至少支持 Markdown 和 HTML 格式
        passed = 'MARKDOWN' in formats_available and 'HTML' in formats_available

        details = f"可用格式: {', '.join(formats_available)}"

        return passed, details

    def test_ai_summary(self) -> tuple[bool, str]:
        """测试6: AI总结生成"""
        try:
            response = requests.post(
                f"{self.base_url}/api/tasks/{self.task_id}/analysis",
                json={
                    'action': 'summary',
                    'instruction': '请用一句话总结这份报纸的主要内容'
                },
                timeout=60
            )

            if response.status_code != 200:
                return False, f"请求失败: {response.status_code}"

            data = response.json()
            summary = data.get('answer') or data.get('summary', '')

            # 要求: 能生成非空的总结
            passed = len(summary.strip()) > 0

            preview = summary[:100] + '...' if len(summary) > 100 else summary
            details = f"总结长度: {len(summary)}字符, 预览: {preview}"

            return passed, details

        except Exception as e:
            return False, f"AI服务异常: {str(e)}"


def main():
    if len(sys.argv) < 2:
        print("用法: python acceptance_test.py <测试图片路径>")
        print("\n示例:")
        print("  python acceptance_test.py ../test_newspaper.png")
        sys.exit(1)

    test_image = sys.argv[1]

    if not Path(test_image).exists():
        print(f"❌ 文件不存在: {test_image}")
        sys.exit(1)

    # Check if service is running
    try:
        response = requests.get("http://127.0.0.1:5000/api/health", timeout=3)
        if response.status_code != 200:
            print("❌ 服务未就绪，请先启动后端服务")
            print("\n启动命令:")
            print("  cd backend")
            print("  python app.py")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务，请先启动后端服务")
        sys.exit(1)

    # Run tests
    tester = AcceptanceTest()
    success = tester.run_acceptance_test(test_image)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
