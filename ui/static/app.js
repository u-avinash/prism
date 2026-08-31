/**
 * ╔══════════════════════════════════════════════════════════════════════╗
 * ║                          P  R  I  S  M                               ║
 * ║       Autonomous AI Incident Management System                       ║
 * ╚══════════════════════════════════════════════════════════════════════╝
 *
 *   Building an Autonomous AI Incident Management System
 *   with LangGraph and OpenTelemetry
 *
 *   Author   : Upadhyayula Avinash
 *   GitHub   : https://github.com/u-avinash
 *   LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
 *   Email    : uavinash.csit@gmail.com
 *
 *   Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
 */
/**
 * Prism UI — app.js
 * Vanilla JS: tabs, toasts, polling, approval actions, trigger, sidebar.
 */

(function () {
  'use strict';

  /* ─────────────────────────────────────────────────────────────────────
   * 1. NAMESPACE
   * ───────────────────────────────────────────────────────────────────── */
  const prism = {};
  window.prism = prism;

  /* ─────────────────────────────────────────────────────────────────────
   * 2. TOAST NOTIFICATIONS
   * ───────────────────────────────────────────────────────────────────── */
  let _toastContainer = null;

  function getToastContainer() {
    if (!_toastContainer) {
      _toastContainer = document.getElementById('toastContainer');
    }
    if (!_toastContainer) {
      _toastContainer = document.createElement('div');
      _toastContainer.id = 'toastContainer';
      _toastContainer.className = 'toast-container';
      _toastContainer.setAttribute('aria-live', 'polite');
      _toastContainer.setAttribute('aria-atomic', 'true');
      document.body.appendChild(_toastContainer);
    }
    return _toastContainer;
  }

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {'success'|'error'|'warning'|'info'} [type='info']
   * @param {number} [duration=4000]
   */
  prism.toast = function (message, type, duration) {
    type = type || 'info';
    duration = duration !== undefined ? duration : 4000;

    const toast = document.createElement('div');
    toast.className = 'toast toast--' + type;
    toast.setAttribute('role', 'alert');

    const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
    toast.innerHTML =
      '<span class="toast-icon">' + (icons[type] || 'ℹ') + '</span>' +
      '<span class="toast-message">' + escapeHtml(message) + '</span>' +
      '<button class="toast-close" aria-label="Dismiss">×</button>';

    toast.querySelector('.toast-close').addEventListener('click', function () {
      removeToast(toast);
    });

    getToastContainer().appendChild(toast);

    // Trigger enter animation
    requestAnimationFrame(function () {
      toast.classList.add('toast--visible');
    });

    if (duration > 0) {
      setTimeout(function () { removeToast(toast); }, duration);
    }
    return toast;
  };

  function removeToast(toast) {
    toast.classList.remove('toast--visible');
    toast.classList.add('toast--out');
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }

  // Global alias so templates can call window.showToast(msg, type)
  window.showToast = function (message, type, duration) {
    return prism.toast(message, type, duration);
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 3. CONFIRMATION MODAL
   * ───────────────────────────────────────────────────────────────────── */

  prism.confirm = function (options) {
    const overlay = document.getElementById('modalOverlay');
    const modalBox = document.getElementById('modalBox');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    const confirmButton = document.getElementById('modalConfirm');
    const cancelButton = document.getElementById('modalCancel');
    const closeButton = document.getElementById('modalClose');

    if (!overlay || !title || !body || !confirmButton || !cancelButton || !closeButton) {
      return Promise.resolve(window.confirm(options.message || 'Are you sure?'));
    }

    const previousFocus = document.activeElement;
    title.textContent = options.title || 'Confirm action';
    body.textContent = options.message || 'Are you sure you want to continue?';
    confirmButton.textContent = options.confirmLabel || 'Confirm';
    confirmButton.className = 'btn ' + (options.danger ? 'btn-danger' : 'btn-primary');
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    confirmButton.focus();

    return new Promise(function (resolve) {
      let settled = false;

      function finish(confirmed) {
        if (settled) return;
        settled = true;
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
        document.removeEventListener('keydown', onKeydown);
        overlay.removeEventListener('click', onOverlayClick);
        confirmButton.removeEventListener('click', onConfirm);
        cancelButton.removeEventListener('click', onCancel);
        closeButton.removeEventListener('click', onCancel);
        if (previousFocus && typeof previousFocus.focus === 'function') {
          previousFocus.focus();
        }
        resolve(confirmed);
      }

      function onConfirm() { finish(true); }
      function onCancel() { finish(false); }
      function onKeydown(event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          finish(false);
          return;
        }

        if (event.key === 'Tab' && modalBox) {
          const focusable = Array.from(modalBox.querySelectorAll(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )).filter(function (element) {
            return !element.hidden && element.offsetParent !== null;
          });
          if (!focusable.length) return;

          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }

      function onOverlayClick(event) {
        if (event.target === overlay) finish(false);
      }

      confirmButton.addEventListener('click', onConfirm);
      cancelButton.addEventListener('click', onCancel);
      closeButton.addEventListener('click', onCancel);
      overlay.addEventListener('click', onOverlayClick);
      document.addEventListener('keydown', onKeydown);
    });
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 4. TAB SWITCHING
   * ───────────────────────────────────────────────────────────────────── */

  /**
   * Wire up a tab group.
   * Tabs: elements with [data-tab="panel-id"]  (children of .tabs)
   * Panels: elements with [data-panel="panel-id"]
   * @param {HTMLElement|string} container  The .tabs element or its id.
   */
  prism.initTabs = function (container) {
    if (typeof container === 'string') {
      container = document.getElementById(container);
    }
    if (!container) return;

    const tabs = Array.from(container.querySelectorAll('[data-tab]'));
    if (!tabs.length) return;

    // Find panels — siblings of the tab container or within the parent
    const parent = container.parentElement;

    function activateTab(targetKey) {
      tabs.forEach(function (btn) {
        const active = btn.dataset.tab === targetKey;
        btn.classList.toggle('tab--active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
      });

      parent.querySelectorAll('[data-panel]').forEach(function (panel) {
        const active = panel.dataset.panel === targetKey;
        panel.hidden = !active;
        panel.classList.toggle('tab-panel--active', active);
      });

      // Persist active tab in sessionStorage keyed by container id
      if (container.id) {
        try { sessionStorage.setItem('tab:' + container.id, targetKey); } catch (e) { /* ignore */ }
      }
    }

    // Restore last active tab
    let initial = tabs[0].dataset.tab;
    if (container.id) {
      try {
        const saved = sessionStorage.getItem('tab:' + container.id);
        if (saved && tabs.some(function (t) { return t.dataset.tab === saved; })) {
          initial = saved;
        }
      } catch (e) { /* ignore */ }
    }
    activateTab(initial);

    tabs.forEach(function (btn) {
      btn.addEventListener('click', function () {
        activateTab(btn.dataset.tab);
      });
      // Keyboard: left/right arrows
      btn.addEventListener('keydown', function (e) {
        const idx = tabs.indexOf(btn);
        if (e.key === 'ArrowRight') { tabs[(idx + 1) % tabs.length].focus(); }
        if (e.key === 'ArrowLeft')  { tabs[(idx - 1 + tabs.length) % tabs.length].focus(); }
      });
    });
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 4. POLLING
   * ───────────────────────────────────────────────────────────────────── */
  let _pollTimer = null;

  /**
   * Poll a JSON endpoint at a fixed interval.
   * @param {string} url
   * @param {number} intervalMs
   * @param {function} callback  Called with the parsed JSON object on each success.
   */
  prism.startPolling = function (url, intervalMs, callback) {
    prism.stopPolling();
    function tick() {
      fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(callback)
        .catch(function (err) { console.warn('[prism] poll error:', url, err); });
    }
    tick(); // immediate first call
    _pollTimer = setInterval(tick, intervalMs);
  };

  prism.stopPolling = function () {
    if (_pollTimer !== null) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 5. APPROVAL ACTIONS
   * ───────────────────────────────────────────────────────────────────── */

  /**
   * Handle approve / reject button clicks inside #approvalForm.
   */
  function initApprovalForm() {
    const form = document.getElementById('approvalForm');
    if (!form) return;

    const incidentId = form.dataset.incident;
    const notesEl = document.getElementById('approvalNotes');

    form.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const action = btn.dataset.action; // 'approve' or 'reject'
        const notes  = notesEl ? notesEl.value.trim() : '';

        const confirmation = action === 'reject' && !notes
          ? prism.confirm({
              title: 'Reject fix without notes?',
              message: 'The incident will be rejected without reviewer feedback.',
              confirmLabel: 'Reject fix',
              danger: true,
            })
          : Promise.resolve(true);

        confirmation.then(function (confirmed) {
          if (!confirmed) return;

          btn.disabled = true;
          btn.textContent = action === 'approve' ? 'Approving…' : 'Rejecting…';

          return fetch('/api/incidents/' + incidentId + '/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'action=' + encodeURIComponent(action) + '&notes=' + encodeURIComponent(notes),
          });
        })
          .then(function (r) {
            if (!r) return null;
            return r.json();
          })
          .then(function (data) {
            if (!data) return;
            if (data.success || data.status || data.ok) {
              prism.toast(
                action === 'approve' ? 'Fix approved — workflow continuing.' : 'Incident rejected.',
                action === 'approve' ? 'success' : 'warning'
              );
              setTimeout(function () { window.location.reload(); }, 1500);
            } else {
              prism.toast('Error: ' + (data.detail || data.message || 'Unknown error'), 'error');
              btn.disabled = false;
              btn.textContent = action === 'approve' ? '✓ Approve Fix' : '✕ Reject';
            }
          })
          .catch(function (err) {
            prism.toast('Request failed: ' + err, 'error');
            btn.disabled = false;
            btn.textContent = action === 'approve' ? '✓ Approve Fix' : '✕ Reject';
          });
      });
    });
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 6. RE-TRIGGER WORKFLOW
   * ───────────────────────────────────────────────────────────────────── */

  function initTriggerBtn() {
    const btn = document.getElementById('triggerBtn');
    if (!btn) return;

    btn.addEventListener('click', function () {
      const incidentId = btn.dataset.incident;
      prism.confirm({
        title: 'Re-trigger workflow?',
        message: 'This will restart the incident workflow for ' + incidentId + '.',
        confirmLabel: 'Re-trigger',
      }).then(function (confirmed) {
        if (!confirmed) return;

        btn.disabled = true;
        btn.textContent = '⏳ Triggering…';

        return fetch('/api/incidents/' + incidentId + '/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
      })
        .then(function (r) {
          if (!r) return null;
          return r.json();
        })
        .then(function (data) {
          if (!data) return;
          if (data.success || data.message || data.ok) {
            prism.toast('Workflow triggered successfully.', 'success');
            setTimeout(function () { window.location.reload(); }, 1500);
          } else {
            prism.toast('Error: ' + (data.detail || 'Could not trigger workflow.'), 'error');
            btn.disabled = false;
            btn.textContent = '⚡ Re-trigger';
          }
        })
        .catch(function (err) {
          prism.toast('Request failed: ' + err, 'error');
          btn.disabled = false;
          btn.textContent = '⚡ Re-trigger';
        });
    });
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 7. PROJECT / APP SWITCHER
   * ───────────────────────────────────────────────────────────────────── */

  function initSwitchers() {
    // Project switcher
    var projectSel = document.getElementById('projectSwitcher');
    if (projectSel) {
      projectSel.addEventListener('change', function () {
        var projectId = this.value;
        if (!projectId) return;
        fetch('/api/switch-project', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: projectId }),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.success) {
              prism.toast('Switched to project: ' + data.project_name, 'success', 2000);
              setTimeout(function () { window.location.reload(); }, 800);
            } else {
              prism.toast(data.message || 'Could not switch project.', 'error');
            }
          })
          .catch(function () { prism.toast('Failed to switch project.', 'error'); });
      });
    }

    // App switcher
    var appSel = document.getElementById('appSwitcher');
    if (appSel) {
      appSel.addEventListener('change', function () {
        var appId = this.value;
        if (!appId) return;
        fetch('/api/switch-app', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ app_id: appId }),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.success) {
              prism.toast('Switched to app: ' + data.app_name, 'success', 2000);
              setTimeout(function () { window.location.reload(); }, 800);
            } else {
              prism.toast(data.message || 'Could not switch app.', 'error');
            }
          })
          .catch(function () { prism.toast('Failed to switch app.', 'error'); });
      });
    }
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 8. REFRESH BUTTON
   * ───────────────────────────────────────────────────────────────────── */

  function initRefreshBtn() {
    var btn = document.getElementById('refreshBtn');
    if (!btn) return;
    btn.addEventListener('click', function (event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      btn.disabled = true;
      btn.textContent = '↻ Refreshing…';

      var url = new URL(window.location.href);
      url.searchParams.set('_refresh', String(Date.now()));
      window.location.href = url.toString();
    });
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 9. SIDEBAR TOGGLE (mobile)
   * ───────────────────────────────────────────────────────────────────── */

  function initSidebar() {
    const toggleBtn = document.getElementById('sidebarToggle');
    const sidebar   = document.querySelector('.sidebar');
    if (!toggleBtn || !sidebar) return;

    toggleBtn.addEventListener('click', function () {
      const open = sidebar.classList.toggle('sidebar--open');
      toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', function (e) {
      if (
        window.innerWidth < 769 &&
        sidebar.classList.contains('sidebar--open') &&
        !sidebar.contains(e.target) &&
        e.target !== toggleBtn
      ) {
        sidebar.classList.remove('sidebar--open');
        toggleBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 10. INCIDENT LIST — live badge refresh
   * ───────────────────────────────────────────────────────────────────── */

  /**
   * Refresh individual incident row badges without a full page reload.
   * Called from the incidents list page polling.
   */
  prism.refreshIncidentRow = function (incidentId, data) {
    const row = document.querySelector('[data-id="' + incidentId + '"]');
    if (!row) return;
    const statusBadge = row.querySelector('.incident-row-status .badge');
    if (statusBadge) {
      statusBadge.textContent = (data.status || 'UNKNOWN').replace(/_/g, ' ');
    }
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 11. DIFF VIEWER — keyboard-accessible expand
   * ───────────────────────────────────────────────────────────────────── */

  function initDiffViewer() {
    const table = document.querySelector('.diff-table');
    if (!table) return;
    // Long diffs: add a "show more" toggle after 200 rows
    const rows = Array.from(table.querySelectorAll('tr'));
    const THRESHOLD = 200;
    if (rows.length <= THRESHOLD) return;

    rows.slice(THRESHOLD).forEach(function (r) { r.hidden = true; });

    const showMore = document.createElement('tr');
    showMore.innerHTML =
      '<td colspan="4" style="text-align:center; padding:8px;">' +
      '<button class="btn btn-ghost btn-sm" id="diffShowMore">' +
      'Show remaining ' + (rows.length - THRESHOLD) + ' lines…</button></td>';
    table.querySelector('tbody').appendChild(showMore);

    document.getElementById('diffShowMore').addEventListener('click', function () {
      rows.slice(THRESHOLD).forEach(function (r) { r.hidden = false; });
      showMore.remove();
    });
  }

  /* ─────────────────────────────────────────────────────────────────────
   * 12. SERVER-SENT EVENTS (workflow live updates)
   * ───────────────────────────────────────────────────────────────────── */

  /**
   * Subscribe to live workflow updates via SSE.
   * The server emits JSON objects: { node, status, message }
   * @param {string} incidentId
   * @param {function} onEvent  Called with each parsed event object.
   */
  prism.subscribeWorkflow = function (incidentId, onEvent) {
    if (!window.EventSource) {
      console.warn('[prism] EventSource not supported; falling back to polling.');
      return null;
    }
    const src = new EventSource('/api/incidents/' + incidentId + '/stream');
    src.onmessage = function (e) {
      try { onEvent(JSON.parse(e.data)); } catch (ex) { /* skip malformed */ }
    };
    src.onerror = function () {
      console.warn('[prism] SSE connection lost for incident', incidentId);
      src.close();
    };
    return src;
  };

  /* ─────────────────────────────────────────────────────────────────────
   * 13. UTILITIES
   * ───────────────────────────────────────────────────────────────────── */

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&')
      .replace(/</g, '<')
      .replace(/>/g, '>')
      .replace(/"/g, '"')
      .replace(/'/g, '&#39;');
  }

  prism.escapeHtml = escapeHtml;

  /* ─────────────────────────────────────────────────────────────────────
   * 14. BOOT
   * ───────────────────────────────────────────────────────────────────── */

  function boot() {
    // Wire up every .tabs container on the page
    document.querySelectorAll('.tabs').forEach(function (el) {
      prism.initTabs(el);
    });

    initRefreshBtn();
    initSwitchers();
    initSidebar();
    initApprovalForm();
    initTriggerBtn();
    initDiffViewer();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
