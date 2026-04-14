// gallery.js - EventDrop gallery selection and bulk operations

(function() {
  'use strict';

  const EVENT_ID = window.EVENT_ID;
  const CAN_DOWNLOAD = window.CAN_DOWNLOAD || false;
  const CAN_DELETE = window.CAN_DELETE || false;

  let selectedIds = new Set();
  let lastClickedIndex = null;
  let allMediaItems = [];

  function init() {
    allMediaItems = Array.from(document.querySelectorAll('.media-item'));

    // Checkbox click handling
    document.querySelectorAll('.media-checkbox').forEach((cb, idx) => {
      cb.addEventListener('change', (e) => {
        const id = cb.dataset.id;
        if (e.shiftKey && lastClickedIndex !== null) {
          // Range selection
          const start = Math.min(lastClickedIndex, idx);
          const end = Math.max(lastClickedIndex, idx);
          const checkboxes = document.querySelectorAll('.media-checkbox');
          for (let i = start; i <= end; i++) {
            const rangeCb = checkboxes[i];
            rangeCb.checked = cb.checked;
            if (cb.checked) {
              selectedIds.add(rangeCb.dataset.id);
            } else {
              selectedIds.delete(rangeCb.dataset.id);
            }
          }
        } else {
          if (cb.checked) {
            selectedIds.add(id);
          } else {
            selectedIds.delete(id);
          }
        }
        lastClickedIndex = idx;
        updateToolbar();
      });
    });

    // Select all button
    const selectAllBtn = document.getElementById('select-all-btn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        const checkboxes = document.querySelectorAll('.media-checkbox');
        const allChecked = selectedIds.size === checkboxes.length;
        checkboxes.forEach(cb => {
          cb.checked = !allChecked;
          if (!allChecked) {
            selectedIds.add(cb.dataset.id);
          } else {
            selectedIds.delete(cb.dataset.id);
          }
        });
        updateToolbar();
      });
    }

    // Toolbar buttons
    const cancelBtn = document.getElementById('cancel-selection-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', clearSelection);

    const downloadBtn = document.getElementById('download-selected-btn');
    if (downloadBtn) downloadBtn.addEventListener('click', downloadSelected);

    const deleteBtn = document.getElementById('delete-selected-btn');
    if (deleteBtn) deleteBtn.addEventListener('click', showDeleteModal);

    const deleteConfirmBtn = document.getElementById('delete-confirm-btn');
    if (deleteConfirmBtn) deleteConfirmBtn.addEventListener('click', deleteSelected);

    const deleteCancelBtn = document.getElementById('delete-cancel-btn');
    if (deleteCancelBtn) deleteCancelBtn.addEventListener('click', hideDeleteModal);

    // Download all button
    const downloadAllBtn = document.getElementById('download-all-btn');
    if (downloadAllBtn) downloadAllBtn.addEventListener('click', downloadAll);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        e.preventDefault();
        const checkboxes = document.querySelectorAll('.media-checkbox');
        checkboxes.forEach(cb => {
          cb.checked = true;
          selectedIds.add(cb.dataset.id);
        });
        updateToolbar();
      }
      if (e.key === 'Escape') {
        clearSelection();
        closeLightbox();
      }
    });

    // Mobile long-press for selection
    allMediaItems.forEach((item) => {
      let pressTimer;
      item.addEventListener('touchstart', () => {
        pressTimer = setTimeout(() => {
          const cb = item.querySelector('.media-checkbox');
          if (cb) {
            cb.checked = !cb.checked;
            if (cb.checked) {
              selectedIds.add(cb.dataset.id);
            } else {
              selectedIds.delete(cb.dataset.id);
            }
            updateToolbar();
          }
        }, 500);
      });
      item.addEventListener('touchend', () => clearTimeout(pressTimer));
      item.addEventListener('touchmove', () => clearTimeout(pressTimer));
    });

    // Lightbox setup
    setupLightbox();

    // Close lightbox modal
    const lightboxClose = document.getElementById('lightbox-close');
    if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);

    const lightbox = document.getElementById('lightbox');
    if (lightbox) lightbox.addEventListener('click', (e) => {
      if (e.target === lightbox) closeLightbox();
    });

    // Close delete modal on backdrop
    const deleteModal = document.getElementById('delete-modal');
    if (deleteModal) deleteModal.addEventListener('click', (e) => {
      if (e.target === deleteModal) hideDeleteModal();
    });
  }

  function updateToolbar() {
    const toolbar = document.getElementById('action-toolbar');
    const countEl = document.getElementById('selected-count');
    const selectAllBtn = document.getElementById('select-all-btn');
    const checkboxes = document.querySelectorAll('.media-checkbox');

    if (countEl) countEl.textContent = selectedIds.size;

    if (selectedIds.size > 0) {
      if (toolbar) toolbar.classList.remove('hidden');
    } else {
      if (toolbar) toolbar.classList.add('hidden');
    }

    if (selectAllBtn) {
      if (selectedIds.size === checkboxes.length && checkboxes.length > 0) {
        selectAllBtn.textContent = 'Deselect All';
      } else {
        selectAllBtn.textContent = 'Select All';
      }
    }
  }

  function clearSelection() {
    selectedIds.clear();
    document.querySelectorAll('.media-checkbox').forEach(cb => { cb.checked = false; });
    updateToolbar();
  }

  function showDeleteModal() {
    const modal = document.getElementById('delete-modal');
    const countEl = document.getElementById('delete-modal-count');
    if (countEl) countEl.textContent = selectedIds.size;
    if (modal) modal.classList.remove('hidden');
  }

  function hideDeleteModal() {
    const modal = document.getElementById('delete-modal');
    if (modal) modal.classList.add('hidden');
  }

  async function deleteSelected() {
    hideDeleteModal();
    const ids = Array.from(selectedIds);

    showToast(`Deleting ${ids.length} items...`, 'info');

    try {
      const res = await fetch(`/api/events/${EVENT_ID}/media/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_ids: ids }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Remove deleted items from DOM
      ids.forEach(id => {
        const item = document.querySelector(`.media-item[data-id="${id}"]`);
        if (item) item.remove();
      });

      clearSelection();
      showToast(`Deleted ${data.deleted} items.`, 'success');

      if (data.errors && data.errors.length > 0) {
        showToast(`${data.errors.length} items could not be deleted.`, 'warning');
      }

      // Update media count
      const countEl = document.getElementById('media-count');
      if (countEl) {
        const remaining = document.querySelectorAll('.media-item').length;
        countEl.textContent = remaining;
      }

    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error');
    }
  }

  async function downloadSelected() {
    const ids = Array.from(selectedIds);
    await triggerDownload(`/api/events/${EVENT_ID}/media/download`, { media_ids: ids });
  }

  async function downloadAll() {
    await triggerDownload(`/api/events/${EVENT_ID}/media/download-all`, {});
  }

  async function triggerDownload(url, body) {
    const overlay = document.getElementById('download-overlay');
    if (overlay) overlay.classList.remove('hidden');

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();

      // Trigger browser download
      const a = document.createElement('a');
      a.href = data.download_url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      showToast(`Download ready! ${data.file_count} files.`, 'success');

    } catch (err) {
      showToast(`Download failed: ${err.message}`, 'error');
    } finally {
      if (overlay) overlay.classList.add('hidden');
    }
  }

  async function deleteSingleItem(mediaId) {
    if (!confirm('Delete this item? This cannot be undone.')) return;

    try {
      const res = await fetch(`/api/events/${EVENT_ID}/media/${mediaId}`, {
        method: 'DELETE',
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const item = document.querySelector(`.media-item[data-id="${mediaId}"]`);
      if (item) item.remove();

      selectedIds.delete(mediaId);
      updateToolbar();
      showToast('Item deleted.', 'success');

    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error');
    }
  }

  window.deleteSingleItem = deleteSingleItem;

  function setupLightbox() {
    document.querySelectorAll('.media-item').forEach(item => {
      const openBtn = item.querySelector('.open-lightbox');
      if (openBtn) {
        openBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          openLightbox(item.dataset.url, item.dataset.type, item.dataset.filename);
        });
      }
    });
  }

  function openLightbox(url, type, filename) {
    const lightbox = document.getElementById('lightbox');
    const imgEl = document.getElementById('lightbox-img');
    const videoEl = document.getElementById('lightbox-video');
    const filenameEl = document.getElementById('lightbox-filename');

    if (!lightbox) return;

    if (type === 'video' || (url && (url.includes('.mp4') || url.includes('.mov') || url.includes('.webm')))) {
      if (imgEl) imgEl.classList.add('hidden');
      if (videoEl) {
        videoEl.src = url;
        videoEl.classList.remove('hidden');
        videoEl.play().catch(() => {});
      }
    } else {
      if (videoEl) {
        videoEl.pause();
        videoEl.src = '';
        videoEl.classList.add('hidden');
      }
      if (imgEl) {
        imgEl.src = url;
        imgEl.classList.remove('hidden');
      }
    }

    if (filenameEl) filenameEl.textContent = filename || '';
    lightbox.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    const lightbox = document.getElementById('lightbox');
    const videoEl = document.getElementById('lightbox-video');
    if (videoEl) {
      videoEl.pause();
      videoEl.src = '';
    }
    if (lightbox) lightbox.classList.add('hidden');
    document.body.style.overflow = '';
  }

  function showToast(message, type) {
    const container = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');
    const colors = {
      success: 'bg-green-600',
      error: 'bg-red-600',
      warning: 'bg-yellow-500',
      info: 'bg-indigo-600',
    };
    toast.className = `${colors[type] || colors.info} text-white px-4 py-3 rounded-lg shadow-lg text-sm max-w-sm transition-opacity duration-300`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed bottom-20 right-4 z-50 flex flex-col gap-2';
    document.body.appendChild(container);
    return container;
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
