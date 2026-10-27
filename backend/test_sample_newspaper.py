#!/usr/bin/env python
"""测试示例报纸 - 返乡运动会之垦殖班"""

import sys
import time
import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:5000"

def create_test_pdf():
    """创建测试PDF（使用临时PNG代替，因为我们有PDF文本但没有实际图像）"""
    # 注意：这里需要实际的PDF文件
    # 用户应该提供实际的PDF文件路径
    print("⚠️  请确保您有实际的PDF文件")
    print("   如果使用图片，可以先转换为图片格式")
    return None

def upload_and_process(file_path):
    """上传并处理报纸"""
    print("=" * 80)
    print("🗞️  测试示例报纸：返乡运动会之垦殖班")
    print("=" * 80)
    print()

    # 1. 上传
    print("📤 步骤1: 上传文件")
    with open(file_path, 'rb') as f:
        files = {'file': (Path(file_path).name, f)}
        data = {'ai_layout': 'true'}
        response = requests.post(
            f"{BASE_URL}/api/tasks",
            files=files,
            data=data,
            timeout=30
        )

        if response.status_code != 202:
            print(f"❌ 上传失败: {response.text}")
            return None

        task = response.json()
        task_id = task['id']
        print(f"✅ 上传成功")
        print(f"   任务ID: {task_id}")
        print(f"   文件名: {task['filename']}")
        print()

    # 2. 等待版面分析
    print("📐 步骤2: 版面分析 (AI增强)")
    if not poll_status(task_id, 'layout_ready', 60):
        return None

    # 获取版面信息
    response = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
    task = response.json()
    total_regions = sum(len(p.get('regions', [])) for p in task.get('pages', []))
    print(f"✅ 版面分析完成")
    print(f"   识别区域: {total_regions} 个")
    print()

    # 3. OCR识别
    print("🔍 步骤3: OCR文字识别")
    response = requests.post(f"{BASE_URL}/api/tasks/{task_id}/ocr", json={})
    if response.status_code != 202:
        print(f"❌ OCR启动失败")
        return None

    if not poll_status(task_id, 'ocr_ready', 180):
        return None

    # 获取OCR结果
    response = requests.get(f"{BASE_URL}/api/tasks/{task_id}/ocr")
    ocr_data = response.json()

    total_chars = 0
    confidences = []
    for page in ocr_data.get('pages', []):
        total_chars += len(page.get('raw_text', ''))
        for region in page.get('regions', []):
            if region.get('confidence'):
                confidences.append(region['confidence'])

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    print(f"✅ OCR识别完成")
    print(f"   识别字符数: {total_chars}")
    print(f"   平均置信度: {avg_confidence:.1%}")
    print()

    # 4. AI校正与文章聚合
    print("🤖 步骤4: AI校正与文章聚合")
    response = requests.post(f"{BASE_URL}/api/tasks/{task_id}/correction", json={})
    if response.status_code != 202:
        print(f"❌ AI校正启动失败")
        return None

    if not poll_status(task_id, 'correction_ready', 240):
        return None

    # 获取校正结果
    response = requests.get(f"{BASE_URL}/api/tasks/{task_id}/correction")
    correction_data = response.json()

    article_ids = set()
    for page in correction_data.get('pages', []):
        for region in page.get('regions', []):
            if region.get('article_id'):
                article_ids.add(region['article_id'])

    print(f"✅ AI校正完成")
    print(f"   识别文章: {len(article_ids)} 篇")
    print()

    # 5. 质量验证
    print("✅ 步骤5: 质量验证")
    response = requests.get(f"{BASE_URL}/api/tasks/{task_id}/validate")
    validation = response.json()

    print(f"   验收结果: {'✅ 通过' if validation.get('passed') else '⚠️ 未完全通过'}")
    print()
    print("   详细指标:")

    # 完整性
    completeness = validation.get('completeness', {})
    print(f"   • 内容完整性: {completeness.get('score', 0):.1%}")
    print(f"     - 总区域: {completeness.get('total_regions', 0)}")
    print(f"     - 空白区域: {completeness.get('empty_regions', 0)}")

    # 准确率
    accuracy = validation.get('accuracy', {})
    print(f"   • 识别准确率: {accuracy.get('score', 0):.1%}")
    print(f"     - 平均置信度: {accuracy.get('avg_confidence', 0):.1%}")
    print(f"     - 高质量区域: {accuracy.get('high_confidence_count', 0)}/{accuracy.get('total_regions', 0)}")

    # 版面质量
    layout = validation.get('layout_quality', {})
    print(f"   • 版面识别质量: {layout.get('score', 0):.1%}")
    print(f"     - AI增强覆盖: {layout.get('ai_enhancement_ratio', 0):.1%}")

    # 文章聚合
    articles = validation.get('article_quality', {})
    print(f"   • 文章聚合:")
    print(f"     - 识别文章: {articles.get('total_articles', 0)} 篇")
    print(f"     - 跨区域文章: {articles.get('multi_region_articles', 0)} 篇")
    print(f"     - 跨页面文章: {articles.get('cross_page_articles', 0)} 篇")
    print()

    # 建议
    if validation.get('recommendations'):
        print("   💡 改进建议:")
        for rec in validation['recommendations']:
            print(f"     • {rec}")
        print()

    # 6. 生成文档
    print("📄 步骤6: 生成最终文档")

    # 测试各种导出格式
    formats_ok = []
    for fmt in ['markdown', 'html', 'json']:
        try:
            response = requests.get(f"{BASE_URL}/api/tasks/{task_id}/export/{fmt}", timeout=30)
            if response.status_code == 200:
                size = len(response.content)
                formats_ok.append(f"{fmt.upper()}({size//1024}KB)")

                # 保存到文件
                output_file = f"test_output_{task_id}.{fmt}"
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                print(f"   ✅ {fmt.upper()} 格式: 已生成并保存到 {output_file}")
        except Exception as e:
            print(f"   ❌ {fmt.upper()} 格式生成失败: {e}")

    print()

    # 7. AI总结
    print("🤖 步骤7: 生成AI总结")
    try:
        response = requests.post(
            f"{BASE_URL}/api/tasks/{task_id}/analysis",
            json={
                'action': 'summary',
                'instruction': '请用2-3句话总结这份民国报纸的主要内容，重点说明提到了哪些重要事件或人物'
            },
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            summary = data.get('answer', data.get('summary', ''))
            print(f"✅ AI总结生成成功:")
            print()
            print("   " + "=" * 70)
            for line in summary.split('\n'):
                print(f"   {line}")
            print("   " + "=" * 70)
            print()
        else:
            print(f"   ⚠️ AI总结生成失败: {response.status_code}")
            print()
    except Exception as e:
        print(f"   ⚠️ AI总结异常: {e}")
        print()

    # 8. 最终总结
    print("=" * 80)
    print("📊 测试总结")
    print("=" * 80)
    print()
    print(f"✅ OCR识别: {total_chars} 字符, 平均置信度 {avg_confidence:.1%}")
    print(f"✅ 版面分析: {total_regions} 个区域")
    print(f"✅ 文章聚合: {len(article_ids)} 篇文章")
    print(f"✅ 质量验证: {'通过' if validation.get('passed') else '部分通过'}")
    print(f"✅ 文档导出: {', '.join(formats_ok)}")
    print()
    print(f"🌐 查看完整结果:")
    print(f"   工作台: {BASE_URL}/#/tasks/{task_id}")
    print(f"   演示界面: {BASE_URL}/demo.html (重新上传)")
    print()
    print("✨ 测试完成!")
    print()

    return task_id

def poll_status(task_id, target_status, timeout=180):
    """轮询任务状态"""
    start_time = time.time()
    last_message = None

    while time.time() - start_time < timeout:
        response = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
        task = response.json()

        # 显示进度信息
        if task.get('progress') and task['progress'].get('message'):
            msg = task['progress']['message']
            if msg != last_message:
                print(f"   {msg}")
                last_message = msg

        if task.get('status') == target_status:
            return True

        if task.get('status', '').startswith('error'):
            print(f"   ❌ 错误: {task.get('error', 'Unknown error')}")
            return False

        time.sleep(2)

    print(f"   ⏱️ 超时等待状态: {target_status}")
    return False

def main():
    if len(sys.argv) < 2:
        print("用法: python test_sample_newspaper.py <PDF文件路径>")
        print()
        print("示例:")
        print("  python test_sample_newspaper.py ../返乡运动会之垦殖班.pdf")
        print("  python test_sample_newspaper.py test_newspaper.png")
        sys.exit(1)

    file_path = sys.argv[1]

    if not Path(file_path).exists():
        print(f"❌ 文件不存在: {file_path}")
        sys.exit(1)

    # 检查服务
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=3)
        if response.status_code != 200:
            print("❌ 服务未就绪")
            sys.exit(1)
    except:
        print("❌ 无法连接到服务，请先启动:")
        print("   cd backend && python app.py")
        sys.exit(1)

    # 运行测试
    task_id = upload_and_process(file_path)

    if task_id:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
