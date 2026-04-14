// upload.js - EventDrop multi-file upload handler

(function() {
  'use strict';

  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const fileList = document.getElementById('file-list');
  const overallProgress = document.getElementById('overall-progress');
  const uploadSummary = document.getElementById('upload-summary');
  const EVENT_ID = window.EVENT_ID;

  if (!dropZone || !fileInput) return;

  let uploadQueue = [];
  let uploadedCount = 0;
  let failedCount = 0;

  // Drag and drop events
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.add('border-indigo-500', 'bg-indigo-50', 'dark:bg-indigo-950');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.remove('border-indigo-500', 'bg-indigo-50', 'dark:bg-indigo-950');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const files = Array.from(e.dataTransfer.files);
    addFilesToQueue(files);
  });

  dropZone.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files);
    addFilesToQueue(files);
    fileInput.value = ''; // reset so same file can be re-added
  });

  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function isImage(file) {
    return file.type.startsWith('image/');
  }

  function isVideo(file) {
    return file.type.startsWith('video/');
  }

  function createFileItem(file, index) {
    const item = document.createElement('div');
    item.id = `file-item-${index}`;
    item.className = 'flex items-center gap-3 p-3 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700';

    // Preview
    const preview = document.createElement('div');
    preview.className = 'w-12 h-12 rounded overflow-hidden flex-shrink-0 bg-slate-100 dark:bg-slate-700 flex items-center justify-center';

    if (isImage(file)) {
      const img = document.createElement('img');
      img.className = 'w-full h-full object-cover';
      const reader = new FileReader();
      reader.onload = (e) => { img.src = e.target.result; };
      reader.readAsDataURL(file);
      preview.appendChild(img);
    } else if (isVideo(file)) {
      preview.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.069A1 1 0 0121 8.917v6.166a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>';
    } else {
      preview.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>';
    }

    // Info
    const info = document.createElement('div');
    info.className = 'flex-1 min-w-0';
    info.innerHTML = `
      <p class="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">${file.name}</p>
      <p class="text-xs text-slate-500 dark:text-slate-400">${formatBytes(file.size)}</p>
      <div id="progress-bar-${index}" class="mt-1 hidden">
        <div class="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5">
          <div id="progress-fill-${index}" class="bg-indigo-600 h-1.5 rounded-full transition-all duration-300" style="width: 0%"></div>
        </div>
      </div>
    `;

    // Status
    const status = document.createElement('div');
    status.id = `status-${index}`;
    status.className = 'flex-shrink-0 text-sm';
    status.innerHTML = '<span class="text-slate-400">Pending</span>';

    item.appendChild(preview);
    item.appendChild(info);
    item.appendChild(status);
    return item;
  }

  function addFilesToQueue(files) {
    files.forEach(file => {
      const index = uploadQueue.length;
      uploadQueue.push({ file, status: 'pending', index });
      const item = createFileItem(file, index);
      fileList.appendChild(item);
    });

    if (fileList.parentElement) {
      fileList.parentElement.classList.remove('hidden');
    }

    processQueue();
  }

  async function processQueue() {
    const pending = uploadQueue.filter(f => f.status === 'pending');
    // Upload up to 3 concurrent
    const uploading = uploadQueue.filter(f => f.status === 'uploading');
    const slots = 3 - uploading.length;

    for (let i = 0; i < Math.min(slots, pending.length); i++) {
      const item = pending[i];
      item.status = 'uploading';
      uploadFile(item);
    }
  }

  async function uploadFile(queueItem) {
    const { file, index } = queueItem;
    const statusEl = document.getElementById(`status-${index}`);
    const progressBar = document.getElementById(`progress-bar-${index}`);
    const progressFill = document.getElementById(`progress-fill-${index}`);

    if (progressBar) progressBar.classList.remove('hidden');
    if (statusEl) statusEl.innerHTML = '<span class="text-indigo-600 dark:text-indigo-400">Uploading...</span>';

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Use XMLHttpRequest for progress tracking
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            if (progressFill) progressFill.style.width = `${pct}%`;
          }
        });

        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText));
          } else {
            let msg = 'Upload failed';
            try {
              msg = JSON.parse(xhr.responseText).detail || msg;
            } catch (_) {}
            reject(new Error(msg));
          }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));

        xhr.open('POST', `/api/e/${EVENT_ID}/upload`);
        xhr.send(formData);
      });

      queueItem.status = 'done';
      uploadedCount++;
      if (progressFill) progressFill.style.width = '100%';
      if (statusEl) statusEl.innerHTML = '<span class="text-green-600 dark:text-green-400">Done</span>';
      const fileItemEl = document.getElementById(`file-item-${index}`);
      if (fileItemEl) fileItemEl.classList.add('border-green-200', 'dark:border-green-800');

    } catch (err) {
      queueItem.status = 'error';
      failedCount++;
      if (statusEl) {
        statusEl.innerHTML = `
          <div class="text-right">
            <span class="text-red-600 dark:text-red-400 text-xs">${err.message}</span>
            <button onclick="retryUpload(${index})" class="block text-xs text-indigo-600 underline mt-0.5">Retry</button>
          </div>`;
      }
      const fileItemEl = document.getElementById(`file-item-${index}`);
      if (fileItemEl) fileItemEl.classList.add('border-red-200', 'dark:border-red-800');
    }

    updateOverallProgress();
    processQueue();
  }

  window.retryUpload = function(index) {
    const item = uploadQueue[index];
    if (!item) return;
    if (item.status !== 'error') return;
    item.status = 'pending';
    failedCount--;
    const statusEl = document.getElementById(`status-${index}`);
    if (statusEl) statusEl.innerHTML = '<span class="text-slate-400">Pending</span>';
    processQueue();
  };

  function updateOverallProgress() {
    const total = uploadQueue.length;
    if (total === 0) return;
    const done = uploadQueue.filter(f => f.status === 'done' || f.status === 'error').length;
    const pct = Math.round((done / total) * 100);

    if (overallProgress) {
      overallProgress.classList.remove('hidden');
      const fill = overallProgress.querySelector('.progress-fill');
      const label = overallProgress.querySelector('.progress-label');
      if (fill) fill.style.width = `${pct}%`;
      if (label) label.textContent = `${done}/${total} files processed`;
    }

    if (done === total && uploadSummary) {
      uploadSummary.classList.remove('hidden');
      const successEl = uploadSummary.querySelector('.success-count');
      const failEl = uploadSummary.querySelector('.fail-count');
      if (successEl) successEl.textContent = uploadedCount;
      if (failEl) failEl.textContent = failedCount;
    }
  }

})();
