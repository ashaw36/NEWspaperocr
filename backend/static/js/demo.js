// 演示系统 JavaScript

const API_BASE = '/api';

const MODULES = [
    { id: 'upload', name: '📤 文件上传', desc: '上传报纸图像文件' },
    { id: 'layout', name: '📐 版面分析', desc: 'AI增强的多栏识别' },
    { id: 'ocr', name: '🔍 OCR识别', desc: 'PaddleOCR文字识别' },
    { id: 'correction', name: '🤖 AI校正', desc: '文章聚合与校正' },
    { id: 'document', name: '📄 文档生成', desc: '生成最终文档' },
    { id: 'summary', name: '💡 AI总结', desc: '智能内容总结' }
];

let currentTaskId = null;
let selectedFile = null;
let pollInterval = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initModules();
    initUpload();
    initTabs();
    initExport();
});

function initModules() {
    const grid = document.getElementById('modulesGrid');
    grid.innerHTML = MODULES.map(module => `
        <div class="module-card" id="module-${module.id}">
            <div class="module-header">
                <div class="module-title">
                    ${module.name}
                    <span class="module-status pending" id="status-${module.id}"></span>
                </div>
            </div>
            <div class="module-content" id="content-${module.id}">
                ${module.desc}
            </div>
            <div class="progress-bar" style="display: none;" id="progress-${module.id}">
                <div class="progress-fill"></div>
            </div>
        </div>
    `).join('');
}

function initUpload() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');
    const processBtn = document.getElementById('processBtn');

    zone.addEventListener('click', () => input.click());

    input.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFileSelect(file);
    });

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) handleFileSelect(file);
    });

    processBtn.addEventListener('click', startProcessing);
}

function handleFileSelect(file) {
    selectedFile = file;
    document.getElementById('uploadZone').innerHTML = `
        <div class="upload-icon">✅</div>
        <h3>${file.name}</h3>
        <p style="color: var(--text-secondary); margin-top: 0.5rem;">
            ${(file.size / 1024 / 1024).toFixed(2)} MB
        </p>
    `;
    document.getElementById('processBtn').disabled = false;
}

async function startProcessing() {
    if (!selectedFile) return;

    document.getElementById('processBtn').disabled = true;
    updateModuleStatus('upload', 'processing', '正在上传...');

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('ai_layout', 'true');

    try {
        const response = await fetch(`${API_BASE}/tasks`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) throw new Error('上传失败');

        const data = await response.json();
        currentTaskId = data.id;

        updateModuleStatus('upload', 'completed', '上传完成');
        showToast('文件上传成功');

        // 开始轮询任务状态
        startPolling();

    } catch (error) {
        updateModuleStatus('upload', 'error', error.message);
        showToast('上传失败: ' + error.message, 'error');
        document.getElementById('processBtn').disabled = false;
    }
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/tasks/${currentTaskId}`);
            const task = await response.json();

            updateTaskStatus(task);

            if (task.status === 'completed' || task.status.startsWith('error')) {
                clearInterval(pollInterval);
                if (task.status === 'completed') {
                    await loadResults();
                }
            }
        } catch (error) {
            console.error('轮询错误:', error);
        }
    }, 2000);
}

function updateTaskStatus(task) {
    const statusMap = {
        'uploaded': { module: 'upload', status: 'completed' },
        'layout_ready': { module: 'layout', status: 'completed' },
        'ocr_ready': { module: 'ocr', status: 'completed' },
        'correction_ready': { module: 'correction', status: 'completed' },
        'completed': { module: 'document', status: 'completed' }
    };

    // 更新当前状态
    if (statusMap[task.status]) {
        const { module, status } = statusMap[task.status];
        updateModuleStatus(module, status);

        // 激活下一个模块
        const nextModuleIndex = MODULES.findIndex(m => m.id === module) + 1;
        if (nextModuleIndex < MODULES.length) {
            const nextModule = MODULES[nextModuleIndex].id;
            if (nextModule !== 'summary') { // summary 单独触发
                updateModuleStatus(nextModule, 'processing');
            }
        }
    }

    // 更新进度消息
    if (task.progress && task.progress.message) {
        const currentModule = MODULES.find(m =>
            task.status.includes(m.id) || task.progress.message.includes(m.name)
        );
        if (currentModule) {
            updateModuleContent(currentModule.id, task.progress.message);
        }
    }
}

function updateModuleStatus(moduleId, status, message) {
    const card = document.getElementById(`module-${moduleId}`);
    const statusEl = document.getElementById(`status-${moduleId}`);

    if (card) {
        card.className = 'module-card ' + status;
    }
    if (statusEl) {
        statusEl.className = 'module-status ' + status;
    }
    if (message) {
        updateModuleContent(moduleId, message);
    }
}

function updateModuleContent(moduleId, message) {
    const contentEl = document.getElementById(`content-${moduleId}`);
    if (contentEl) {
        contentEl.textContent = message;
    }
}

async function loadResults() {
    document.getElementById('resultsSection').classList.add('show');

    // 加载 OCR 文本
    try {
        const response = await fetch(`${API_BASE}/tasks/${currentTaskId}/ocr`);
        const data = await response.json();

        let text = '';
        data.pages.forEach((page, i) => {
            text += `=== 第 ${i + 1} 页 ===\n\n`;
            text += page.raw_text + '\n\n';
        });

        document.getElementById('ocrText').textContent = text;
    } catch (error) {
        document.getElementById('ocrText').textContent = '加载失败: ' + error.message;
    }

    // 加载质量报告
    try {
        const response = await fetch(`${API_BASE}/tasks/${currentTaskId}/validate`);
        const validation = await response.json();

        const metricsHTML = `
            <div class="metric-card">
                <div class="metric-value">${(validation.completeness?.score * 100 || 0).toFixed(1)}%</div>
                <div class="metric-label">内容完整性</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">${(validation.accuracy?.score * 100 || 0).toFixed(1)}%</div>
                <div class="metric-label">识别准确率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">${(validation.layout_quality?.score * 100 || 0).toFixed(1)}%</div>
                <div class="metric-label">版面质量</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">${validation.article_quality?.total_articles || 0}</div>
                <div class="metric-label">识别文章</div>
            </div>
        `;

        document.getElementById('qualityMetrics').innerHTML = metricsHTML;
    } catch (error) {
        console.error('加载质量报告失败:', error);
    }

    // 生成 AI 总结
    updateModuleStatus('summary', 'processing', '正在生成总结...');
    try {
        const response = await fetch(`${API_BASE}/tasks/${currentTaskId}/analysis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'summary',
                instruction: '请用2-3句话总结这份报纸的主要内容，重点说明提到了哪些重要事件或人物'
            })
        });

        const data = await response.json();
        const summary = data.answer || data.summary || '生成失败';

        document.getElementById('summaryText').textContent = summary;
        updateModuleStatus('summary', 'completed', '总结完成');

    } catch (error) {
        document.getElementById('summaryText').textContent = '生成失败: ' + error.message;
        updateModuleStatus('summary', 'error', '总结失败');
    }

    showToast('所有处理已完成！');
}

function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;

            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`tab-${tab}`).classList.add('active');
        });
    });
}

function initExport() {
    document.querySelectorAll('.export-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!currentTaskId) return;

            const format = btn.dataset.format;
            try {
                const response = await fetch(`${API_BASE}/tasks/${currentTaskId}/export/${format}`);
                if (!response.ok) throw new Error('导出失败');

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `newspaper_${currentTaskId}.${format}`;
                a.click();
                window.URL.revokeObjectURL(url);

                showToast(`${format.toUpperCase()} 文件已下载`);
            } catch (error) {
                showToast('导出失败: ' + error.message, 'error');
            }
        });
    });
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}
