/* meridian.js — Scroll-reveal observer. No dependencies. */
window.__meridianFetchJsonWithTimeout = window.__meridianFetchJsonWithTimeout || async function (url, timeoutMs) {
  var controller = new AbortController();
  var timeout = window.setTimeout(function () {
    controller.abort();
  }, Math.max(300, timeoutMs || 6000));
  try {
    var response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(url + ' returned HTTP ' + response.status);
    }
    return await response.json();
  } finally {
    window.clearTimeout(timeout);
  }
};

(function () {
  'use strict';
  var els = document.querySelectorAll('.reveal');
  if (!els.length) {
    return;
  }
  // Keep structure visible immediately; observer now only normalizes class state.
  els.forEach(function (el) { el.classList.add('visible'); });
  if (!('IntersectionObserver' in window)) {
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach(function (el) { io.observe(el); });
})();

/* Pilot/checkout browser handlers removed in open-source mode.
   The public site now uses contribution-first onboarding, not purchase flows. */


(function () {
  'use strict';
  var shell = document.querySelector('[data-trust-ops-shell]');
  if (!shell) {
    return;
  }

  var TOKEN_STORAGE_KEY = 'meridian.trustOps.operatorToken';
  var TOKEN_REMEMBER_KEY = 'meridian.trustOps.rememberToken';
  var filterForm = shell.querySelector('[data-trust-ops-filter-form]');
  var statusNode = shell.querySelector('[data-trust-ops-status]');
  var queueBody = shell.querySelector('[data-trust-ops-queue-body]');
  var questionnaireDetail = shell.querySelector('[data-trust-ops-questionnaire-detail]');
  var questionnaireSelect = shell.querySelector('[name="questionnaire_id"]');
  var summaryActionable = shell.querySelector('[data-summary-actionable]');
  var summaryPending = shell.querySelector('[data-summary-pending]');
  var summaryReady = shell.querySelector('[data-summary-ready]');
  var summaryEvidence = shell.querySelector('[data-summary-evidence]');
  var authForm = shell.querySelector('[data-trust-ops-auth-form]');
  var authStatusNode = shell.querySelector('[data-trust-ops-auth-status]');
  var authTokenInput = shell.querySelector('[name="operator_token"]');
  var rememberTokenInput = shell.querySelector('[name="remember_token"]');
  var clearTokenButton = shell.querySelector('[data-trust-ops-clear-token]');
  var bulkBar = shell.querySelector('[data-trust-ops-bulk-bar]');
  var selectAllCheckbox = shell.querySelector('[data-trust-ops-select-all]');
  var selectedCountNode = shell.querySelector('[data-trust-ops-selected-count]');
  var currentSnapshot = null;
  var selectedQueueIds = new Set();
  var operatorToken = '';

  function setOperatorStatus(message, isError) {
    if (!statusNode) {
      return;
    }
    statusNode.textContent = message;
    statusNode.style.color = isError ? '#ff9b9b' : '';
  }

  function setAuthStatus(message, isError) {
    if (!authStatusNode) {
      return;
    }
    authStatusNode.textContent = message;
    authStatusNode.style.color = isError ? '#ff9b9b' : '';
  }

  function safeText(value) {
    return value == null ? '' : String(value);
  }

  function escapeHtml(value) {
    return safeText(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatTimestamp(value) {
    if (!value) {
      return 'Not reviewed yet';
    }
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return safeText(value);
    }
    return date.toLocaleString();
  }

  function badgeClass(bucket) {
    if (bucket === 'pending' || bucket === 'stale') {
      return 'status-warn';
    }
    if (bucket === 'revoked') {
      return 'status-bad';
    }
    if (bucket === 'approved') {
      return 'status-good';
    }
    return 'status-neutral';
  }

  function requestHeaders(extraHeaders) {
    var headers = extraHeaders || {};
    if (operatorToken) {
      headers.Authorization = 'Bearer ' + operatorToken;
      headers['X-Meridian-Operator-Token'] = operatorToken;
    }
    return headers;
  }

  async function trustOpsFetch(url, options) {
    var config = options ? Object.assign({}, options) : {};
    var headers = {};
    if (config.headers) {
      Object.keys(config.headers).forEach(function (key) {
        headers[key] = config.headers[key];
      });
    }
    config.headers = requestHeaders(headers);
    var targetUrl = safeText(url);
    if (/^\//.test(targetUrl)) {
      targetUrl = new URL(targetUrl, window.location.origin).toString();
    }
    return fetch(targetUrl, config);
  }

  function persistOperatorToken(token) {
    var normalizedToken = safeText(token).trim();
    var remember = Boolean(rememberTokenInput && rememberTokenInput.checked);
    operatorToken = normalizedToken;
    try {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      if (normalizedToken) {
        if (remember) {
          localStorage.setItem(TOKEN_STORAGE_KEY, normalizedToken);
        } else {
          sessionStorage.setItem(TOKEN_STORAGE_KEY, normalizedToken);
        }
      }
      localStorage.setItem(TOKEN_REMEMBER_KEY, remember ? 'true' : 'false');
    } catch (error) {
      // Ignore storage errors.
    }
  }

  function restoreOperatorToken() {
    var storedToken = '';
    var remember = false;
    try {
      storedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
      remember = localStorage.getItem(TOKEN_REMEMBER_KEY) === 'true';
    } catch (error) {
      storedToken = '';
      remember = false;
    }
    operatorToken = safeText(storedToken).trim();
    if (rememberTokenInput) {
      rememberTokenInput.checked = remember;
    }
    if (authTokenInput) {
      authTokenInput.value = operatorToken ? '••••••••••••••••' : '';
    }
    if (operatorToken) {
      setAuthStatus('Saved operator token is active for this browser session.', false);
    } else {
      setAuthStatus('Operator token required.', false);
    }
  }

  function clearOperatorToken() {
    operatorToken = '';
    selectedQueueIds.clear();
    try {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(TOKEN_REMEMBER_KEY);
    } catch (error) {
      // Ignore storage errors.
    }
    if (authTokenInput) {
      authTokenInput.value = '';
    }
    if (rememberTokenInput) {
      rememberTokenInput.checked = false;
    }
    if (queueBody) {
      queueBody.innerHTML = '<tr><td colspan="7">Operator token required to load queue data.</td></tr>';
    }
    if (questionnaireDetail) {
      questionnaireDetail.innerHTML = '<p class="dim">Unlock the queue to inspect questionnaire detail.</p>';
    }
    currentSnapshot = null;
    setOperatorStatus('Operator token required to read Trust Ops state.', true);
    setAuthStatus('Operator token cleared.', false);
    syncBulkSelectionUi();
  }

  function showLockedTrustOpsState(authMessage, statusMessage, authError) {
    if (queueBody) {
      queueBody.innerHTML = '<tr><td colspan="7">Operator token required to load queue data.</td></tr>';
    }
    if (questionnaireDetail) {
      questionnaireDetail.innerHTML = '<p class="dim">Unlock the queue to inspect questionnaire detail.</p>';
    }
    currentSnapshot = null;
    setOperatorStatus(statusMessage || 'Operator token required to read Trust Ops state.', true);
    setAuthStatus(authMessage || 'Operator token required.', Boolean(authError));
    syncBulkSelectionUi();
  }

  function renderQuestionnaireOptions(operator) {
    if (!questionnaireSelect) {
      return;
    }
    var selected = operator && operator.filters ? operator.filters.questionnaire_id || '' : '';
    var options = ['<option value="">All questionnaires</option>'];
    (operator && operator.questionnaires ? operator.questionnaires : []).forEach(function (item) {
      var qid = safeText(item.questionnaire_id);
      var selectedAttr = qid === selected ? ' selected' : '';
      options.push('<option value="' + escapeHtml(qid) + '"' + selectedAttr + '>' + escapeHtml(qid) + '</option>');
    });
    questionnaireSelect.innerHTML = options.join('');
  }

  function renderSummary(operator) {
    var summary = operator && operator.summary ? operator.summary : {};
    var counts = operator && operator.counts ? operator.counts : {};
    var evidenceCounts = summary && summary.evidence && summary.evidence.counts ? summary.evidence.counts : {};
    if (summaryActionable) {
      summaryActionable.textContent = String(counts.actionable || 0);
    }
    if (summaryPending) {
      summaryPending.textContent = String(counts.pending || summary.pending_queue_count || 0);
    }
    if (summaryReady) {
      summaryReady.textContent = String(summary.ready_questionnaire_count || 0);
    }
    if (summaryEvidence) {
      summaryEvidence.textContent = [
        evidenceCounts.approved || 0,
        evidenceCounts.draft || 0,
        evidenceCounts.stale || 0,
        evidenceCounts.revoked || 0
      ].join(' / ');
    }
  }

  function visibleQueueIds() {
    var queue = currentSnapshot && currentSnapshot.queue ? currentSnapshot.queue : [];
    return queue.map(function (item) { return safeText(item.queue_id).trim(); }).filter(Boolean);
  }

  function syncBulkSelectionUi() {
    if (!bulkBar || !selectedCountNode) {
      return;
    }
    var visibleIds = visibleQueueIds();
    var visibleSet = new Set(visibleIds);
    Array.from(selectedQueueIds).forEach(function (queueId) {
      if (!visibleSet.has(queueId)) {
        selectedQueueIds.delete(queueId);
      }
    });
    var selectedCount = selectedQueueIds.size;
    selectedCountNode.textContent = String(selectedCount) + ' selected';
    bulkBar.hidden = !visibleIds.length;
    if (selectAllCheckbox) {
      selectAllCheckbox.checked = Boolean(visibleIds.length) && visibleIds.every(function (queueId) {
        return selectedQueueIds.has(queueId);
      });
      selectAllCheckbox.indeterminate = Boolean(selectedCount) && !selectAllCheckbox.checked;
    }
    Array.prototype.forEach.call(shell.querySelectorAll('[data-queue-select]'), function (checkbox) {
      var queueId = safeText(checkbox.getAttribute('data-queue-select')).trim();
      checkbox.checked = selectedQueueIds.has(queueId);
    });
    Array.prototype.forEach.call(shell.querySelectorAll('[data-bulk-decision]'), function (button) {
      button.disabled = !selectedCount;
      var wrapper = button.closest('.bulk-action-wrapper');
      if (wrapper) {
        if (!selectedCount) {
          wrapper.setAttribute('tabindex', '0');
          wrapper.setAttribute('title', 'Select items to enable bulk actions');
        } else {
          wrapper.removeAttribute('tabindex');
          wrapper.removeAttribute('title');
        }
      }
    });
  }

  function renderQueue(operator) {
    var rows = operator && operator.queue ? operator.queue : [];
    if (!queueBody) {
      return;
    }
    if (!rows.length) {
      queueBody.innerHTML = '<tr><td colspan="7">No queue items match the current filter.</td></tr>';
      syncBulkSelectionUi();
      return;
    }
    queueBody.innerHTML = rows.map(function (item) {
      var bucket = safeText(item.bucket);
      var reviewMeta = item.reviewed_at
        ? '<div class="operator-meta">Reviewed by ' + escapeHtml(item.reviewed_by || 'operator') + ' · ' + escapeHtml(formatTimestamp(item.reviewed_at)) + '</div>'
        : '<div class="operator-meta">No explicit review recorded yet.</div>';
      var noteMeta = item.review_note
        ? '<div class="operator-meta">' + escapeHtml(item.review_note) + '</div>'
        : '';
      var questionMeta = [
        item.critical ? '<span class="operator-chip operator-chip-critical">Critical</span>' : '<span class="operator-chip">Standard</span>',
        item.approval_required ? '<span class="operator-chip operator-chip-action">Approval required</span>' : '<span class="operator-chip">Delivery allowed</span>'
      ].join(' ');
      var actionButtons = ['approve', 'stale', 'revoke', 'unresolved'].map(function (decision) {
        return '<button type="button" class="operator-action" data-queue-id="' + escapeHtml(item.queue_id) + '" data-decision="' + decision + '" aria-label="' + escapeHtml(decision) + ' queue item ' + escapeHtml(item.queue_id) + '">' + escapeHtml(decision) + '</button>';
      }).join('');
      return '<tr>' +
        '<td data-label="Select" class="operator-select-cell"><input type="checkbox" aria-label="Select queue item ' + escapeHtml(item.queue_id) + '" data-queue-select="' + escapeHtml(item.queue_id) + '"></td>' +
        '<td data-label="Question"><strong>' + escapeHtml(item.question_text || item.question_id) + '</strong><div class="operator-meta">' + questionMeta + '</div>' + noteMeta + '</td>' +
        '<td data-label="State"><span class="' + badgeClass(bucket) + '">' + escapeHtml(bucket) + '</span><div class="operator-meta">Gate: ' + escapeHtml(item.approval_gate_status || 'unknown') + '</div></td>' +
        '<td data-label="Evidence"><code>' + escapeHtml(item.evidence_key || 'none') + '</code><div class="operator-meta">Status: ' + escapeHtml(item.evidence_status || 'none') + '</div></td>' +
        '<td data-label="Owner"><strong>' + escapeHtml(item.origin_agent || 'main') + '</strong>' + reviewMeta + '</td>' +
        '<td data-label="Questionnaire"><button type="button" class="operator-link" data-select-questionnaire="' + escapeHtml(item.questionnaire_id) + '">' + escapeHtml(item.questionnaire_id) + '</button><div class="operator-meta">' + escapeHtml(item.source_session_key || '') + '</div></td>' +
        '<td data-label="Action"><div class="operator-actions">' + actionButtons + '</div></td>' +
      '</tr>';
    }).join('');
    syncBulkSelectionUi();
  }

  function renderQuestionnaireDetail(operator) {
    if (!questionnaireDetail) {
      return;
    }
    var selected = operator ? operator.selected_questionnaire : null;
    if (!selected) {
      questionnaireDetail.innerHTML = '<p class="dim">No questionnaire selected yet.</p>';
      return;
    }
    var questions = selected.questions || [];
    var questionItems = questions.map(function (item) {
      var bucket = item.approval_required ? 'pending' : (item.answer_state || 'unknown');
      var evidenceLine = item.evidence_key
        ? '<div class="operator-meta">Evidence: <code>' + escapeHtml(item.evidence_key) + '</code> · ' + escapeHtml(item.evidence_status || 'unknown') + '</div>'
        : '<div class="operator-meta">No evidence key linked.</div>';
      var reviewLine = item.last_reviewed_at
        ? '<div class="operator-meta">Last review: ' + escapeHtml(item.last_review_decision || 'reviewed') + ' · ' + escapeHtml(formatTimestamp(item.last_reviewed_at)) + '</div>'
        : '';
      var resolutionLine = item.resolution_note
        ? '<div class="operator-meta">' + escapeHtml(item.resolution_note) + '</div>'
        : '';
      return '<article class="operator-question-card">' +
        '<div class="operator-question-head"><strong>' + escapeHtml(item.text || item.question_id) + '</strong><span class="' + badgeClass(bucket) + '">' + escapeHtml(bucket) + '</span></div>' +
        '<div class="operator-meta">Owner: ' + escapeHtml(item.origin_agent || 'main') + (item.critical ? ' · Critical' : '') + '</div>' +
        evidenceLine + reviewLine + resolutionLine +
      '</article>';
    }).join('');
    questionnaireDetail.innerHTML =
      '<div class="operator-detail-head">' +
        '<div><strong>' + escapeHtml(selected.questionnaire_id) + '</strong><div class="operator-meta">' + escapeHtml(selected.source_session_key || '') + '</div></div>' +
        '<div class="operator-detail-metrics">' +
          '<span class="' + badgeClass(selected.pending_approval_count ? 'pending' : 'approved') + '">' + escapeHtml(selected.approval_gate_status || 'unknown') + '</span>' +
          '<span class="operator-chip">' + escapeHtml(String(selected.pending_approval_count || 0)) + ' pending</span>' +
          '<span class="operator-chip">' + escapeHtml(String(selected.critical_count || 0)) + ' critical</span>' +
        '</div>' +
      '</div>' +
      '<div class="operator-question-grid">' + questionItems + '</div>';
  }

  function buildOperatorStatusMessage(operator) {
    var filters = operator && operator.filters ? operator.filters : {};
    var queue = operator && operator.queue ? operator.queue : [];
    var questionnaires = operator && operator.questionnaires ? operator.questionnaires : [];
    var selectedQuestionnaire = filters.questionnaire_id || '';
    var filterLabelMap = {
      actionable: 'actionable items',
      all: 'all visible items',
      pending: 'pending approvals',
      approved: 'approved items',
      stale: 'stale items',
      revoked: 'revoked items',
      unresolved: 'unresolved items',
      draft: 'draft items'
    };
    var filterLabel = filterLabelMap[filters.status] || 'queue items';
    var parts = [
      'Trust Ops queue loaded.',
      'Showing ' + String(queue.length) + ' ' + filterLabel + '.'
    ];
    if (selectedQuestionnaire) {
      parts.push('Focused on ' + selectedQuestionnaire + '.');
    } else if (questionnaires.length) {
      parts.push('Tracking ' + String(questionnaires.length) + ' questionnaires.');
    }
    if (filters.include_cleared) {
      parts.push('Cleared items included.');
    }
    return parts.join(' ');
  }

  async function loadOperatorSnapshot() {
    var params = new URLSearchParams();
    var formData = new FormData(filterForm);
    formData.forEach(function (value, key) {
      if (key === 'include_cleared') {
        return;
      }
      if (value) {
        params.set(key, value);
      }
    });
    var includeCleared = filterForm.querySelector('[name="include_cleared"]');
    if (includeCleared && includeCleared.checked) {
      params.set('include_cleared', 'true');
    }
    setOperatorStatus('Refreshing Trust Ops queue…', false);
    try {
      var response = await trustOpsFetch('/api/trust-ops/queue?' + params.toString());
      var payload = await response.json();
      if (response.status === 401) {
        if (operatorToken) {
          clearOperatorToken();
          setAuthStatus('Operator token was rejected. Paste a valid token to continue.', true);
        } else {
          showLockedTrustOpsState(
            'Operator token required. Browser auth alone was not enough for queue access.',
            'Operator token required to read Trust Ops state.',
            false
          );
        }
        return;
      }
      if (!response.ok) {
        throw new Error(payload && payload.output ? payload.output : 'Failed to load Trust Ops queue');
      }
      currentSnapshot = payload.operator || null;
      renderQuestionnaireOptions(currentSnapshot);
      renderSummary(currentSnapshot);
      renderQueue(currentSnapshot);
      renderQuestionnaireDetail(currentSnapshot);
      setOperatorStatus(buildOperatorStatusMessage(currentSnapshot), false);
      setAuthStatus('Trust Ops queue unlocked.', false);
    } catch (error) {
      setOperatorStatus(error.message || 'Failed to load Trust Ops queue', true);
      if (queueBody) {
        queueBody.innerHTML = '<tr><td colspan="7">Could not load queue.</td></tr>';
      }
      if (questionnaireDetail) {
        questionnaireDetail.innerHTML = '<p class="dim">Could not load questionnaire detail.</p>';
      }
      syncBulkSelectionUi();
    }
  }

  async function reviewQueueItem(queueId, decision) {
    var note = window.prompt('Review note for ' + decision + ' on ' + queueId + ':', '');
    if (note === null) {
      return;
    }
    setOperatorStatus('Submitting ' + decision + ' review for ' + queueId + '…', false);
    try {
      var response = await trustOpsFetch('/api/trust-ops/queue/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          queue_id: queueId,
          decision: decision,
          note: note,
          actor: 'web-operator'
        })
      });
      var payload = await response.json();
      if (response.status === 401) {
        if (operatorToken) {
          clearOperatorToken();
          setAuthStatus('Operator token was rejected. Paste a valid token to continue.', true);
        } else {
          showLockedTrustOpsState(
            'Operator token required before queue review can run.',
            'Operator token required to review queue items.',
            false
          );
        }
        return;
      }
      if (!response.ok) {
        throw new Error(payload && payload.output ? payload.output : 'Queue review failed');
      }
      setOperatorStatus('Queue item ' + queueId + ' reviewed as ' + decision + '.', false);
      await loadOperatorSnapshot();
    } catch (error) {
      setOperatorStatus(error.message || 'Queue review failed', true);
    }
  }

  async function bulkReviewQueue(decision) {
    var queueIds = Array.from(selectedQueueIds);
    if (!queueIds.length) {
      return;
    }
    var note = window.prompt('Review note for bulk ' + decision + ' on ' + String(queueIds.length) + ' queue item(s):', '');
    if (note === null) {
      return;
    }
    setOperatorStatus('Submitting bulk ' + decision + ' review for ' + String(queueIds.length) + ' queue item(s)…', false);
    try {
      var response = await trustOpsFetch('/api/trust-ops/queue/bulk-review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          queue_ids: queueIds,
          decision: decision,
          note: note,
          actor: 'web-operator'
        })
      });
      var payload = await response.json();
      if (response.status === 401) {
        if (operatorToken) {
          clearOperatorToken();
          setAuthStatus('Operator token was rejected. Paste a valid token to continue.', true);
        } else {
          showLockedTrustOpsState(
            'Operator token required before bulk review can run.',
            'Operator token required to review queue items.',
            false
          );
        }
        return;
      }
      if (!response.ok) {
        throw new Error(payload && payload.output ? payload.output : 'Bulk queue review failed');
      }
      selectedQueueIds.clear();
      var summary = payload && payload.bulk_review ? payload.bulk_review.summary || {} : {};
      setOperatorStatus(
        'Bulk review completed: ' + String(summary.reviewed_count || 0) + ' reviewed, ' + String((summary.failed_queue_ids || []).length || 0) + ' failed.',
        false
      );
      await loadOperatorSnapshot();
    } catch (error) {
      setOperatorStatus(error.message || 'Bulk queue review failed', true);
    }
  }

  filterForm.addEventListener('submit', function (event) {
    event.preventDefault();
    loadOperatorSnapshot();
  });

  if (authForm) {
    authForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var submittedToken = authTokenInput ? authTokenInput.value.trim() : '';
      if (!submittedToken || submittedToken === '••••••••••••••••') {
        if (!operatorToken) {
          setAuthStatus('Paste a valid operator token to unlock queue data.', true);
          return;
        }
        loadOperatorSnapshot();
        return;
      }
      persistOperatorToken(submittedToken);
      if (authTokenInput) {
        authTokenInput.value = '••••••••••••••••';
      }
      setAuthStatus('Operator token stored. Syncing queue…', false);
      loadOperatorSnapshot();
    });
  }

  if (clearTokenButton) {
    clearTokenButton.addEventListener('click', function () {
      clearOperatorToken();
    });
  }

  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', function () {
      visibleQueueIds().forEach(function (queueId) {
        if (selectAllCheckbox.checked) {
          selectedQueueIds.add(queueId);
        } else {
          selectedQueueIds.delete(queueId);
        }
      });
      syncBulkSelectionUi();
    });
  }

  shell.addEventListener('click', function (event) {
    var selectButton = event.target.closest('[data-select-questionnaire]');
    if (selectButton && questionnaireSelect) {
      questionnaireSelect.value = selectButton.getAttribute('data-select-questionnaire') || '';
      loadOperatorSnapshot();
      return;
    }
    var actionButton = event.target.closest('[data-queue-id][data-decision]');
    if (actionButton) {
      reviewQueueItem(
        actionButton.getAttribute('data-queue-id') || '',
        actionButton.getAttribute('data-decision') || ''
      );
      return;
    }
    var bulkButton = event.target.closest('[data-bulk-decision]');
    if (bulkButton) {
      bulkReviewQueue(bulkButton.getAttribute('data-bulk-decision') || '');
    }
  });

  shell.addEventListener('change', function (event) {
    var queueCheckbox = event.target.closest('[data-queue-select]');
    if (queueCheckbox) {
      var queueId = safeText(queueCheckbox.getAttribute('data-queue-select')).trim();
      if (queueCheckbox.checked) {
        selectedQueueIds.add(queueId);
      } else {
        selectedQueueIds.delete(queueId);
      }
      syncBulkSelectionUi();
    }
  });

  restoreOperatorToken();
  if (!operatorToken) {
    showLockedTrustOpsState('Operator token required.', 'Operator token required to read Trust Ops state.', false);
  }
  loadOperatorSnapshot();
})();

(function () {
  'use strict';
  if (document.body && document.body.classList.contains('page-home')) {
    return;
  }
  var shells = document.querySelectorAll('[data-live-snapshot]');
  if (!shells.length) {
    return;
  }
  var LIVE_SNAPSHOT_CACHE_KEY = 'meridian.live_snapshot.v1';
  var LIVE_SNAPSHOT_CACHE_MAX_AGE_MS = 10 * 60 * 1000;
  var latestSnapshot = null;

  function readSnapshotCache() {
    if (!window.localStorage) {
      return null;
    }
    try {
      var raw = window.localStorage.getItem(LIVE_SNAPSHOT_CACHE_KEY);
      if (!raw) {
        return null;
      }
      var parsed = JSON.parse(raw);
      var savedAt = Number(parsed && parsed.saved_at_unix_ms);
      if (!Number.isFinite(savedAt)) {
        return null;
      }
      if (Date.now() - savedAt > LIVE_SNAPSHOT_CACHE_MAX_AGE_MS) {
        return null;
      }
      var payload = parsed && parsed.payload ? parsed.payload : null;
      if (!payload || typeof payload !== 'object') {
        return null;
      }
      return payload;
    } catch (_error) {
      return null;
    }
  }

  function writeSnapshotCache(payload) {
    if (!window.localStorage) {
      return;
    }
    try {
      window.localStorage.setItem(
        LIVE_SNAPSHOT_CACHE_KEY,
        JSON.stringify({
          saved_at_unix_ms: Date.now(),
          payload: payload || {},
        })
      );
    } catch (_error) {
      // Cache write failure should never block rendering.
    }
  }

  latestSnapshot = readSnapshotCache();

  function safeNumber(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function metricStatusScore(value) {
    if (value === 'healthy') {
      return 100;
    }
    if (value === 'warning') {
      return 64;
    }
    if (value === 'breach') {
      return 18;
    }
    return 36;
  }

  function renderChart(target, items) {
    if (!target) {
      return;
    }
    if (!items || !items.length) {
      target.innerHTML = '<div class="live-chart-empty">No live data available yet. The dashboard refreshes every 15 seconds.</div>';
      return;
    }
    var max = 1;
    items.forEach(function (item) {
      var candidate = safeNumber(item.max || item.value || 0);
      if (candidate > max) {
        max = candidate;
      }
    });
    var rowHeight = 34;
    var width = 320;
    var height = 18 + items.length * rowHeight;
    var barMax = 132;
    var lines = [];
    lines.push('<svg class="live-chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Live Meridian chart">');
    items.forEach(function (item, index) {
      var y = 18 + index * rowHeight;
      var value = safeNumber(item.value || 0);
      var barWidth = Math.max(8, Math.round((value / max) * barMax));
      var fillColor = item.warn
        ? 'rgba(255,183,77,0.88)'
        : 'rgba(135,216,255,0.88)';
      lines.push('<text x="0" y="' + y + '" fill="#dce7f4" font-size="11" font-family="IBM Plex Mono, monospace">' + item.label + '</text>');
      lines.push('<rect x="118" y="' + (y - 10) + '" width="' + barMax + '" height="8" fill="rgba(255,255,255,0.07)"></rect>');
      lines.push('<rect x="118" y="' + (y - 10) + '" width="' + barWidth + '" height="8" fill="' + fillColor + '"></rect>');
      lines.push('<text x="266" y="' + y + '" fill="#7f8a99" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="end">' + item.display + '</text>');
    });
    lines.push('</svg>');
    target.innerHTML = lines.join('');
  }

  function renderLoadingChart(target) {
    if (!target) {
      return;
    }
    target.innerHTML = [
      '<div class="live-chart-skeleton" aria-hidden="true">',
      '<div class="live-chart-skeleton-row"><span class="live-chart-skeleton-label"></span><span class="live-chart-skeleton-bar"></span><span class="live-chart-skeleton-value"></span></div>',
      '<div class="live-chart-skeleton-row"><span class="live-chart-skeleton-label"></span><span class="live-chart-skeleton-bar"></span><span class="live-chart-skeleton-value"></span></div>',
      '<div class="live-chart-skeleton-row"><span class="live-chart-skeleton-label"></span><span class="live-chart-skeleton-bar"></span><span class="live-chart-skeleton-value"></span></div>',
      '</div>'
    ].join('');
  }

  function setCaption(shell, name, text) {
    var node = shell.querySelector('[data-live-caption="' + name + '"]');
    if (node) {
      node.textContent = text;
    }
  }

  function setLoadingState(shell, message) {
    ['runtime', 'queue', 'proof'].forEach(function (name) {
      setCaption(shell, name, message);
      renderLoadingChart(shell.querySelector('[data-live-chart="' + name + '"]'));
    });
  }
  var fetchJsonWithTimeout = window.__meridianFetchJsonWithTimeout;

  function renderSnapshotIntoShell(shell, status, proof) {
    var runtimeItems = [
      {
        label: 'agents',
        value: safeNumber(proof && proof.health ? proof.health.agent_count : 0),
        max: 10,
        display: String(safeNumber(proof && proof.health ? proof.health.agent_count : 0))
      },
      {
        label: 'sessions',
        value: safeNumber(proof && proof.health ? proof.health.session_total : 0),
        max: Math.max(140, safeNumber(proof && proof.health ? proof.health.session_total : 0)),
        display: String(safeNumber(proof && proof.health ? proof.health.session_total : 0))
      },
      {
        label: 'channels',
        value: safeNumber(proof && proof.runtime_surfaces && proof.runtime_surfaces.channel_runtime ? proof.runtime_surfaces.channel_runtime.total_count : 0),
        max: 4,
        display: String(safeNumber(proof && proof.runtime_surfaces && proof.runtime_surfaces.channel_runtime ? proof.runtime_surfaces.channel_runtime.total_count : 0))
      }
    ];
    renderChart(shell.querySelector('[data-live-chart="runtime"]'), runtimeItems);
    setCaption(
      shell,
      'runtime',
      'Live runtime reports ' +
        String(runtimeItems[0].value) +
        ' governed agents, ' +
        String(runtimeItems[1].value) +
        ' sessions, and ' +
        String(runtimeItems[2].value) +
        ' active channels.'
    );

    var queueMax = Math.max(6, safeNumber(status.queue_count), safeNumber(status.pending_delivery_count), safeNumber(status.delivered_count));
    var queueItems = [
      {
        label: 'queue',
        value: safeNumber(status.queue_count),
        max: queueMax,
        display: String(safeNumber(status.queue_count)),
        warn: safeNumber(status.queue_count) > 0
      },
      {
        label: 'pending',
        value: safeNumber(status.pending_delivery_count),
        max: queueMax,
        display: String(safeNumber(status.pending_delivery_count)),
        warn: safeNumber(status.pending_delivery_count) > 0
      },
      {
        label: 'delivered',
        value: safeNumber(status.delivered_count),
        max: queueMax,
        display: String(safeNumber(status.delivered_count))
      }
    ];
    renderChart(shell.querySelector('[data-live-chart="queue"]'), queueItems);
    setCaption(
      shell,
      'queue',
      'Current queue snapshot: ' +
        String(queueItems[0].value) +
        ' queued, ' +
        String(queueItems[1].value) +
        ' pending deliveries, ' +
        String(queueItems[2].value) +
        ' delivered.'
    );

    var sloStatus = status && status.slo ? status.slo.status : 'unknown';
    var proofItems = [
      {
        label: 'runtime',
        value: metricStatusScore(proof && proof.health ? proof.health.status : 'unknown'),
        max: 100,
        display: proof && proof.health ? String(proof.health.status || 'unknown') : 'unknown',
        warn: proof && proof.health && proof.health.status !== 'healthy'
      },
      {
        label: 'service',
        value: metricStatusScore(proof && proof.runtime_health ? proof.runtime_health.status : 'unknown'),
        max: 100,
        display: proof && proof.runtime_health ? String(proof.runtime_health.status || 'unknown') : 'unknown',
        warn: proof && proof.runtime_health && proof.runtime_health.status !== 'healthy'
      },
      {
        label: 'slo',
        value: metricStatusScore(sloStatus),
        max: 100,
        display: String(sloStatus),
        warn: sloStatus !== 'healthy'
      }
    ];
    renderChart(shell.querySelector('[data-live-chart="proof"]'), proofItems);
    var alerts = safeNumber(status && status.slo ? status.slo.alert_count : 0);
    setCaption(
      shell,
      'proof',
      'Proof boundary is ' +
        (proof && proof.health ? String(proof.health.status || 'unknown') : 'unknown') +
        '; SLO is ' +
        String(sloStatus) +
        ' with ' +
        String(alerts) +
        ' active alert' +
        (alerts === 1 ? '' : 's') +
        '.'
    );
  }

  var snapshotFetchedAt = null;

  if (latestSnapshot && latestSnapshot.status && latestSnapshot.proof) {
    snapshotFetchedAt = new Date();
    shells.forEach(function (shell) {
      renderSnapshotIntoShell(shell, latestSnapshot.status, latestSnapshot.proof);
    });
  }

  async function loadLiveSnapshot() {
    if (!latestSnapshot) {
      shells.forEach(function (shell) {
        setLoadingState(shell, 'Refreshing live host data (15s cadence). Displaying the latest verified sample.');
      });
    }
    try {
      var status = await fetchJsonWithTimeout('/api/status', 6000);
      var proof = {};
      try {
        proof = await fetchJsonWithTimeout('/api/runtime-proof', 7000);
      } catch (_proofError) {
        proof = {};
      }
      latestSnapshot = { status: status, proof: proof };
      snapshotFetchedAt = new Date();
      writeSnapshotCache(latestSnapshot);
      shells.forEach(function (shell) {
        renderSnapshotIntoShell(shell, status, proof);
      });
    } catch (error) {
      shells.forEach(function (shell) {
        if (latestSnapshot) {
          renderSnapshotIntoShell(shell, latestSnapshot.status, latestSnapshot.proof);
          var staleLabel = snapshotFetchedAt
            ? 'Using last verified sample from ' + snapshotFetchedAt.toLocaleTimeString() + '. Refresh failed: ' + (error.message || 'unknown')
            : 'Using last verified sample. Refresh failed: ' + (error.message || 'unknown');
          setCaption(shell, 'runtime', staleLabel);
        } else {
          ['runtime', 'queue', 'proof'].forEach(function (name) {
            setCaption(shell, name, 'Live data unavailable. Check that the Meridian gateway is running, or try refreshing.');
          });
          renderLoadingChart(shell.querySelector('[data-live-chart="runtime"]'));
          renderLoadingChart(shell.querySelector('[data-live-chart="queue"]'));
          renderLoadingChart(shell.querySelector('[data-live-chart="proof"]'));
        }
      });
    }
  }

  loadLiveSnapshot();
  window.setInterval(loadLiveSnapshot, 15000);
})();

(function () {
  'use strict';
  var summaryShell = document.querySelector('[data-proof-summary-shell]');
  var streamLog = document.querySelector('[data-operator-stream-log]');
  if (!summaryShell && !streamLog) {
    return;
  }

  function safeText(value) {
    return value == null ? '' : String(value);
  }

  function safeNumber(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatUsd(value) {
    return '$' + safeNumber(value).toFixed(2);
  }

  function escapeHtml(value) {
    return safeText(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setText(selector, value) {
    var node = document.querySelector(selector);
    if (node) {
      node.textContent = safeText(value);
    }
  }

  function setStreamMode(label, note, warning) {
    var modeNode = document.querySelector('[data-stream-mode]');
    var noteNode = document.querySelector('[data-stream-note]');
    if (modeNode) {
      modeNode.textContent = safeText(label);
      modeNode.className = warning ? 'status-warn' : 'status-good';
    }
    if (noteNode) {
      noteNode.textContent = safeText(note);
    }
  }

  function appendStreamEvent(eventName, payload) {
    if (!streamLog) {
      return;
    }
    var text = safeText(payload && payload.text ? payload.text : '');
    var source = safeText(payload && payload.source ? payload.source : eventName || 'event');
    if (!text) {
      return;
    }
    var line = document.createElement('div');
    line.className = 'operator-stream-line';
    line.innerHTML =
      '<span class="operator-stream-ts">' + new Date().toLocaleTimeString() + '</span>' +
      '<span class="operator-stream-source">' + escapeHtml(source) + '</span>' +
      '<span class="operator-stream-text">' + escapeHtml(text) + '</span>';
    streamLog.prepend(line);
    var rows = streamLog.querySelectorAll('.operator-stream-line');
    for (var idx = 80; idx < rows.length; idx += 1) {
      rows[idx].remove();
    }
    var empty = streamLog.querySelector('.operator-stream-empty');
    if (empty) {
      empty.remove();
    }
  }

  var summaryFetchedAt = null;
  var lastGoodSummary = null;
  var fetchJsonWithTimeout = window.__meridianFetchJsonWithTimeout;

  function renderSummary(status, proof) {
    if (!summaryShell) {
      return;
    }
    lastGoodSummary = { status: status, proof: proof };
    summaryFetchedAt = new Date();
    setText('[data-proof-runtime-id]', proof.runtime_id || status.runtime_id || 'unknown');
    setText('[data-proof-type]', proof.proof_type || status.proof_mode || 'unknown');
    setText('[data-proof-slo]', (status.slo && status.slo.status) || 'unknown');
    setText('[data-proof-alerts]', safeNumber(status.slo && status.slo.alert_count));
    setText('[data-proof-cash]', formatUsd(status.treasury && status.treasury.balance_usd));
    setText('[data-proof-floor]', formatUsd(status.treasury && status.treasury.reserve_floor_usd));
    var serverTime = safeText(proof.checked_at || (status.slo && status.slo.evaluated_at) || '');
    var timeLabel = serverTime
      ? 'Server ' + serverTime + ' · client ' + new Date().toLocaleTimeString()
      : 'Updated ' + new Date().toLocaleString();
    var runtimeHealth = safeText(
      (proof && proof.runtime_health && proof.runtime_health.status) ||
      (status && status.runtime_proof && status.runtime_proof.channel_surface_status) ||
      'unknown'
    );
    var proofHealth = safeText(
      (proof && proof.health && proof.health.status) ||
      (status && status.runtime_proof && status.runtime_proof.runtime_proof_status) ||
      'unknown'
    );
    setText('[data-proof-updated-at]', timeLabel + ' · runtime ' + runtimeHealth + ' · proof ' + proofHealth);
  }

  async function refreshSummary() {
    if (!summaryShell) {
      return;
    }
    try {
      var status = await fetchJsonWithTimeout('/api/status', 6000);
      var proof = {};
      try {
        proof = await fetchJsonWithTimeout('/api/runtime-proof', 7000);
      } catch (_proofError) {
        proof = {};
      }
      var treasury = status && typeof status === 'object' && status.treasury && typeof status.treasury === 'object'
        ? status.treasury
        : {};
      if (!Number.isFinite(Number(treasury.balance_usd)) || !Number.isFinite(Number(treasury.reserve_floor_usd))) {
        try {
          var treasuryFallback = await fetchJsonWithTimeout('/api/treasury', 6000);
          status.treasury = status.treasury && typeof status.treasury === 'object' ? status.treasury : {};
          status.treasury.balance_usd = Number(treasuryFallback && treasuryFallback.balance_usd) || 0;
          status.treasury.reserve_floor_usd = Number(treasuryFallback && treasuryFallback.reserve_floor_usd) || 0;
        } catch (_treasuryError) {
          // Keep status payload unchanged when treasury fallback is unavailable.
        }
      }
      renderSummary(status, proof);
    } catch (error) {
      if (lastGoodSummary) {
    var staleLabel = summaryFetchedAt
          ? 'Using last verified summary from ' + summaryFetchedAt.toLocaleTimeString() + '. Refresh failed: ' + safeText(error && error.message)
          : 'Using last verified summary. Refresh failed: ' + safeText(error && error.message);
        setText('[data-proof-updated-at]', staleLabel);
      } else {
        setText('[data-proof-updated-at]', 'Live proof summary unavailable: ' + safeText(error && error.message));
      }
    }
  }

  async function hydrateRecentEvents() {
    if (!streamLog) {
      return;
    }
    try {
      var response = await fetch('/api/events');
      if (!response.ok) {
        return;
      }
      var payload = await response.json();
      var events = payload && payload.events ? payload.events : [];
      events.forEach(function (item) {
        appendStreamEvent('history', item);
      });
    } catch (_error) {
      // Best-effort hydration only.
    }
  }

  var pollTimer = null;
  async function pollEventsOnce() {
    try {
      var response = await fetch('/api/events');
      if (!response.ok) {
        throw new Error('poll failed');
      }
      var payload = await response.json();
      var events = payload && payload.events ? payload.events : [];
      events.forEach(function (item) {
        appendStreamEvent('poll', item);
      });
    } catch (error) {
      setStreamMode('polling', 'Realtime stream unavailable. Polling fallback active.', true);
    }
  }

  function startPollingFallback() {
    if (pollTimer) {
      return;
    }
    setStreamMode('polling', 'Realtime stream unavailable. Polling /api/events every 4 seconds.', true);
    pollEventsOnce();
    pollTimer = window.setInterval(pollEventsOnce, 4000);
  }

  function connectEventStream() {
    if (!streamLog) {
      return;
    }
    if (!('EventSource' in window)) {
      startPollingFallback();
      return;
    }
    setStreamMode('stream', 'Connecting to /api/events/stream…', false);
    var source = new EventSource('/api/events/stream');
    source.addEventListener('open', function () {
      setStreamMode('stream', 'Realtime stream active on /api/events/stream.', false);
    });
    source.addEventListener('event', function (event) {
      try {
        var payload = JSON.parse(event.data || '{}');
        appendStreamEvent('stream', payload);
      } catch (error) {
        appendStreamEvent('stream', { source: 'gateway', text: safeText(event.data || '') });
      }
    });
    source.addEventListener('heartbeat', function () {
      setStreamMode('stream', 'Realtime stream active on /api/events/stream.', false);
    });
    source.onerror = function () {
      source.close();
      startPollingFallback();
    };
  }

  refreshSummary();
  window.setInterval(refreshSummary, 15000);
  hydrateRecentEvents();
  connectEventStream();
})();

(function () {
  'use strict';
  var shell = document.querySelector('[data-usdc-surface]');
  if (!shell) {
    return;
  }
  var showcaseGrid = document.querySelector('[data-workflow-showcase-grid]');
  var showcaseUpdatedAt = document.querySelector('[data-workflow-showcase-updated-at]');
  var WORKFLOW_SHOWCASE_CACHE_KEY = 'meridian.workflow_showcase.v1';
  var WORKFLOW_SHOWCASE_CACHE_MAX_AGE_MS = 15 * 60 * 1000;
  var latestShowcase = null;

  function safeNumber(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function setMetric(selector, value) {
    var node = document.querySelector(selector);
    if (node) {
      node.textContent = value;
    }
  }

  function formatUsd(value) {
    return '$' + safeNumber(value).toFixed(2);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function readShowcaseCache() {
    if (!window.localStorage) {
      return null;
    }
    try {
      var raw = window.localStorage.getItem(WORKFLOW_SHOWCASE_CACHE_KEY);
      if (!raw) {
        return null;
      }
      var parsed = JSON.parse(raw);
      var savedAt = Number(parsed && parsed.saved_at_unix_ms);
      if (!Number.isFinite(savedAt)) {
        return null;
      }
      if (Date.now() - savedAt > WORKFLOW_SHOWCASE_CACHE_MAX_AGE_MS) {
        return null;
      }
      var payload = parsed && parsed.payload ? parsed.payload : null;
      if (!payload || typeof payload !== 'object') {
        return null;
      }
      return payload;
    } catch (_error) {
      return null;
    }
  }

  function writeShowcaseCache(showcase) {
    if (!window.localStorage) {
      return;
    }
    try {
      window.localStorage.setItem(
        WORKFLOW_SHOWCASE_CACHE_KEY,
        JSON.stringify({
          saved_at_unix_ms: Date.now(),
          payload: showcase || {},
        })
      );
    } catch (_error) {
      // Cache write failure should never block rendering.
    }
  }

  function renderWorkflowShowcase(showcase) {
    latestShowcase = showcase || null;
    if (!showcaseGrid) {
      return;
    }
    var workflows = showcase && Array.isArray(showcase.workflows) ? showcase.workflows : [];
    if (!workflows.length) {
      showcaseGrid.innerHTML = '<article class="feature-card"><h3>No workflow data</h3><p>No live showcase payload was returned by the gateway.</p></article>';
      if (showcaseUpdatedAt) {
        showcaseUpdatedAt.textContent = 'Workflow showcase unavailable.';
      }
      return;
    }
    function renderWorkflowExtra(item) {
      if (!item) {
        return '';
      }
      if (item.workflow_id === 'governed_memory_relay') {
        return '' +
          '<p><strong>Fork latest:</strong> ' + escapeHtml(item.fork_latest_status || 'missing') + '</p>' +
          '<p><strong>Replay latest:</strong> ' + escapeHtml(item.replay_latest_status || 'missing') + '</p>' +
          '<p><strong>Authority:</strong> ' + escapeHtml(item.replay_authority_status || '-') + '</p>';
      }
      if (item.workflow_id === 'provider_runtime_alignment') {
        return '' +
          '<p><strong>Selected:</strong> ' + escapeHtml(item.selected_provider || '-') + ' / ' + escapeHtml(item.selected_model || '-') + ' (' + escapeHtml(item.selected_transport || '-') + ')</p>' +
          '<p><strong>Active route:</strong> ' + escapeHtml(item.active_provider || '-') + ' / ' + escapeHtml(item.active_model || '-') + ' (' + escapeHtml(item.active_transport || '-') + ')</p>' +
          '<p><strong>Drift:</strong> ' + escapeHtml(Array.isArray(item.drift_fields) ? item.drift_fields.join(', ') : '-') + '</p>';
      }
      if (item.workflow_id === 'memory_tag_taxonomy') {
        return '' +
          '<p><strong>Tag count:</strong> ' + escapeHtml(item.operator_value) + '</p>' +
          '<p><strong>Tags:</strong> ' + escapeHtml(Array.isArray(item.tags) && item.tags.length ? item.tags.join(', ') : '(none)') + '</p>';
      }
      return '';
    }
    showcaseGrid.innerHTML = workflows.map(function (item) {
      var hooks = Array.isArray(item.proof_hooks) ? item.proof_hooks.join(', ') : '';
      return '' +
        '<article class="feature-card">' +
          '<h3>' + escapeHtml(item.title) + '</h3>' +
          '<p><strong>Status:</strong> ' + escapeHtml(item.status) + '</p>' +
          '<p><strong>Signal:</strong> ' + escapeHtml(item.operator_signal) + ' = ' + escapeHtml(item.operator_value) + '</p>' +
          renderWorkflowExtra(item) +
          '<p><strong>Proof hooks:</strong> ' + escapeHtml(hooks) + '</p>' +
        '</article>';
    }).join('');
    if (showcaseUpdatedAt) {
      var phase = showcase && showcase.payout_phase ? showcase.payout_phase : {};
      showcaseUpdatedAt.textContent =
        'Runtime ' + String(showcase.runtime_id || 'unknown') +
        ', proof ' + String(showcase.proof_type || 'unknown') +
        ', payout gate ' + (phase.execution_gate_ok ? 'open' : 'blocked') +
        ' (updated ' + new Date().toLocaleString() + ').';
    }
  }

  latestShowcase = readShowcaseCache();
  if (latestShowcase) {
    renderWorkflowShowcase(latestShowcase);
  }

  var showcaseFetchedAt = null;

  async function refreshWorkflowShowcase() {
    if (!showcaseGrid) {
      return null;
    }
    try {
      var response = await fetch('/api/workflows/showcase');
      if (!response.ok) {
        throw new Error('workflow showcase unavailable');
      }
      var payload = await response.json();
      var showcase = payload && payload.showcase ? payload.showcase : {};
      renderWorkflowShowcase(showcase);
      showcaseFetchedAt = new Date();
      writeShowcaseCache(showcase);
      return showcase;
    } catch (error) {
      if (latestShowcase) {
        if (showcaseUpdatedAt) {
          var staleLabel = showcaseFetchedAt
            ? 'Using last verified showcase from ' + showcaseFetchedAt.toLocaleTimeString() + '. Refresh failed: ' + escapeHtml(String(error && error.message || ''))
            : 'Using last verified showcase. Refresh failed: ' + escapeHtml(String(error && error.message || ''));
          showcaseUpdatedAt.textContent = staleLabel;
        }
      } else {
        showcaseGrid.innerHTML = '<article class="feature-card"><h3>Workflow showcase error</h3><p>' +
          escapeHtml(String(error && error.message || 'unknown_error')) +
          '</p></article>';
        if (showcaseUpdatedAt) {
          showcaseUpdatedAt.textContent = 'Live showcase unavailable: unable to load /api/workflows/showcase.';
        }
      }
      return null;
    }
  }

  function applyUsdFromShowcase(showcase) {
    if (!showcase || typeof showcase !== 'object') {
      return false;
    }
    var balance = safeNumber(showcase.treasury_balance_usd);
    var floor = safeNumber(showcase.treasury_reserve_floor_usd);
    var orders = safeNumber(showcase.paid_orders);
    var payouts = safeNumber(showcase.payout_proposals);
    setMetric('[data-usdc-balance]', formatUsd(balance));
    setMetric('[data-usdc-floor]', formatUsd(floor));
    setMetric('[data-usdc-orders]', String(orders));
    setMetric('[data-usdc-payouts]', String(payouts));
    setMetric(
      '[data-usdc-updated-at]',
      'Updated ' + new Date().toLocaleString() +
        ' from /api/workflows/showcase.'
    );
    return true;
  }

  async function refreshUsdSurface() {
    if (applyUsdFromShowcase(latestShowcase)) {
      return;
    }
    try {
      var responses = await Promise.all([
        fetch('/api/treasury'),
        fetch('/api/payouts')
      ]);
      if (!responses[0].ok || !responses[1].ok) {
        throw new Error('treasury routes unavailable');
      }
      var treasury = await responses[0].json();
      var payouts = await responses[1].json();
      var proposals = payouts && Array.isArray(payouts.proposals) ? payouts.proposals : [];

      setMetric('[data-usdc-balance]', formatUsd(treasury.balance_usd));
      setMetric('[data-usdc-floor]', formatUsd(treasury.reserve_floor_usd));
      setMetric('[data-usdc-orders]', String(safeNumber(treasury.paid_orders)));
      setMetric('[data-usdc-payouts]', String(proposals.length));
      setMetric('[data-usdc-updated-at]', 'Updated ' + new Date().toLocaleString() + ' from /api/treasury and /api/payouts.');
    } catch (error) {
      if (!applyUsdFromShowcase(latestShowcase)) {
        setMetric('[data-usdc-updated-at]', 'Unable to load USDC surface: ' + String(error && error.message || 'unknown_error'));
      }
    }
  }

  async function refreshWorkflowAndUsdSurface() {
    await refreshWorkflowShowcase();
    await refreshUsdSurface();
  }

  refreshWorkflowAndUsdSurface();
  window.setInterval(refreshUsdSurface, 20000);
  window.setInterval(refreshWorkflowAndUsdSurface, 20000);
})();

(function () {
  'use strict';
  var hasInstitutionStatus = document.querySelector('[data-institution-status]');
  var hasCourtTable = document.querySelector('[data-court-rules-body]') || document.querySelector('[data-court-proposals-body]');
  var hasProofExplorer = document.querySelector('[data-proof-explorer]');
  var hasMarketplacePanel = document.querySelector('[data-marketplace-panel]');
  var hasSideHustlePanel = document.querySelector('[data-side-hustle-panel]');
  var hasCommonwealthPanel = document.querySelector('[data-commonwealth-panel]');
  var hasPublicDirectoryShell = document.querySelector('[data-public-directory-shell]');
  var startDemoHustleButton = document.querySelector('[data-start-demo-hustle]');
  var isPublicHomepage = Boolean(document.body && document.body.classList.contains('page-home'));
  if (!hasInstitutionStatus && !hasCourtTable && !hasProofExplorer && !hasMarketplacePanel && !hasSideHustlePanel && !hasCommonwealthPanel && !hasPublicDirectoryShell) {
    return;
  }

  function safeNumber(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatUsd(value) {
    return '$' + safeNumber(value).toFixed(2);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setAll(selector, value) {
    document.querySelectorAll(selector).forEach(function (node) {
      node.textContent = value;
    });
  }

  function toArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function firstNonEmpty(values, fallback) {
    for (var i = 0; i < values.length; i += 1) {
      var candidate = values[i];
      if (candidate != null && String(candidate).trim() !== '') {
        return String(candidate);
      }
    }
    return fallback;
  }

  async function fetchJson(url) {
    if (typeof window.__meridianFetchJsonWithTimeout === 'function') {
      return window.__meridianFetchJsonWithTimeout(url, 7000);
    }
    var response = await fetch(url);
    if (!response.ok) {
      throw new Error(url + ' returned HTTP ' + response.status);
    }
    return response.json();
  }

  function renderInstitutionStatus(statusPayload, runtimeProofPayload) {
    var treasury = statusPayload && statusPayload.treasury ? statusPayload.treasury : {};
    var dynamic = statusPayload && statusPayload.court && statusPayload.court.dynamic ? statusPayload.court.dynamic : {};
    var proofHealth = runtimeProofPayload && runtimeProofPayload.health ? runtimeProofPayload.health : {};
    var objectives = toArray(statusPayload && statusPayload.slo && statusPayload.slo.objectives);
    var sanctionObjective = objectives.find(function (item) {
      return item && item.name === 'governance_sanction_clean';
    }) || {};
    var activeSanctions = safeNumber(sanctionObjective.active_sanctions);

    setAll('[data-inst-treasury-balance]', formatUsd(treasury.balance_usd));
    setAll(
      '[data-inst-treasury-note]',
      'reserve floor ' + formatUsd(treasury.reserve_floor_usd)
    );
    setAll(
      '[data-inst-court-health]',
      firstNonEmpty([statusPayload && statusPayload.slo && statusPayload.slo.status], 'unknown')
    );
    setAll(
      '[data-inst-court-note]',
      'rules v' + firstNonEmpty([dynamic.ruleset_version], '0') +
        ' · proposals ' + firstNonEmpty([dynamic.proposal_count], '0')
    );
    setAll(
      '[data-inst-agent-count]',
      String(safeNumber(proofHealth.agent_count))
    );
    setAll(
      '[data-inst-agent-note]',
      firstNonEmpty([proofHealth.status], 'unknown') + ' runtime state'
    );
    setAll('[data-inst-last-sanction]', activeSanctions > 0 ? (activeSanctions + ' active') : 'none active');
    setAll(
      '[data-inst-sanction-note]',
      activeSanctions > 0
        ? 'Court sanctions are active and require remediation.'
        : 'No active sanctions in the latest governance evaluation.'
    );
    setAll('[data-inst-updated-at]', 'Institution status updated ' + new Date().toLocaleString() + '. Runtime context remains workspace-bound.');
  }

  function renderCourtRules(rulesPayload) {
    var body = document.querySelector('[data-court-rules-body]');
    if (!body) {
      return;
    }
    var rules = toArray(rulesPayload && rulesPayload.rules);
    if (!rules.length) {
      body.innerHTML = '<tr><td colspan="3">No active rules returned.</td></tr>';
      return;
    }
    body.innerHTML = rules.map(function (rule) {
      return '<tr>' +
        '<td>' + escapeHtml(firstNonEmpty([rule.rule_id, rule.id], 'unknown')) + '</td>' +
        '<td>' + escapeHtml(firstNonEmpty([rule.version], 'n/a')) + '</td>' +
        '<td>' + escapeHtml(firstNonEmpty([rule.status], 'active')) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderCourtProposals(proposalPayload) {
    var body = document.querySelector('[data-court-proposals-body]');
    if (!body) {
      return;
    }
    var proposals = toArray(proposalPayload && proposalPayload.proposals);
    if (!proposals.length) {
      body.innerHTML = '<tr><td colspan="3">No proposals currently open.</td></tr>';
      return;
    }
    body.innerHTML = proposals.map(function (proposal) {
      var votes = proposal && proposal.votes ? proposal.votes : {};
      var yes = safeNumber(votes.approve || votes.yes);
      var no = safeNumber(votes.reject || votes.no);
      return '<tr>' +
        '<td>' + escapeHtml(firstNonEmpty([proposal.title, proposal.proposal_id], 'Untitled proposal')) + '</td>' +
        '<td>' + escapeHtml(firstNonEmpty([proposal.status], 'draft')) + '</td>' +
        '<td>' + escapeHtml('yes ' + yes + ' / no ' + no) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderProofExplorer(statusPayload, kernelBundle) {
    if (!hasProofExplorer) {
      return;
    }
    var recursive = statusPayload && statusPayload.proof && statusPayload.proof.recursive ? statusPayload.proof.recursive : {};
    var aggregate = statusPayload && statusPayload.proof && statusPayload.proof.aggregate ? statusPayload.proof.aggregate : {};
    var bundleAggregate = kernelBundle && kernelBundle.aggregate ? kernelBundle.aggregate : {};
    var recursiveRoot = firstNonEmpty([recursive.root], 'not-yet-materialized');
    var inclusionVerified = bundleAggregate.inclusion_verified;
    var inclusionStatus = inclusionVerified === true ? 'verified' : (inclusionVerified === false ? 'failed' : 'unknown');
    var inclusionProofs = toArray(bundleAggregate.inclusion_proofs);

    setAll('[data-proof-recursive-root]', recursiveRoot);
    setAll('[data-proof-recursive-depth]', String(safeNumber(recursive.depth)));
    setAll('[data-proof-recursive-enabled]', String(Boolean(recursive.enabled)));
    setAll('[data-proof-bundle-id]', firstNonEmpty([aggregate.bundle_id, bundleAggregate.bundle_id], 'unknown'));
    setAll('[data-proof-member-count]', String(safeNumber(aggregate.member_count || bundleAggregate.member_count)));
    setAll('[data-proof-integrity-prefix]', firstNonEmpty([aggregate.integrity_hash, bundleAggregate.integrity_hash], '--').slice(0, 16) + '…');
    setAll('[data-proof-inclusion-status]', inclusionStatus);
    setAll(
      '[data-proof-inclusion-note]',
      inclusionProofs.length
        ? ('sample path count ' + inclusionProofs.length + ' from kernel proof bundle')
        : 'No inclusion paths returned by kernel proof bundle.'
    );
  }

  function renderMarketplacePanel(statusPayload, marketplacePayload) {
    if (!hasMarketplacePanel) {
      return;
    }
    var fromStatus = statusPayload && statusPayload.marketplace ? statusPayload.marketplace : {};
    var marketState = marketplacePayload && marketplacePayload.status ? marketplacePayload.status : fromStatus;
    var bids = toArray(marketplacePayload && marketplacePayload.bids);
    var settlements = toArray(marketplacePayload && marketplacePayload.settlements);
    var disputes = toArray(marketplacePayload && marketplacePayload.disputes);
    var latest = (settlements[settlements.length - 1] || disputes[disputes.length - 1] || bids[bids.length - 1] || null);
    var latestText = latest
      ? ('Latest ID ' + firstNonEmpty([latest.id], 'unknown') + ' · status ' + firstNonEmpty([latest.status], 'n/a'))
      : 'No marketplace records yet.';

    setAll('[data-market-open-bids]', String(safeNumber(marketState.open_bids)));
    setAll('[data-market-active-assignments]', String(safeNumber(marketState.active_assignments)));
    setAll('[data-market-settled]', String(safeNumber(marketState.settled_count)));
    setAll('[data-market-open-disputes]', String(safeNumber(marketState.open_disputes)));
    setAll('[data-marketplace-latest-event]', latestText);
  }

  function renderSideHustlePanel(statusPayload, marketplacePayload) {
    if (!hasSideHustlePanel) {
      return;
    }
    var settlements = toArray(marketplacePayload && marketplacePayload.settlements);
    var activeCount = 0;
    var earnings = 0.0;
    var latestProof = 'No proof receipt yet.';
    var recentCount = Math.min(settlements.length, 5);

    settlements.forEach(function (s) {
      if (s.split && s.split.worker_usd) {
        earnings += Number(s.split.worker_usd) || 0;
      } else if (s.split && s.split.total_usd) {
        earnings += Number(s.split.total_usd) || 0;
      }
      if (s.proof_receipt) {
        latestProof = String(s.proof_receipt).slice(0, 16) + '…';
      }
    });

    var successRate = settlements.length > 0 ? '100%' : '0%';

    setAll('[data-hustle-active-count]', String(activeCount));
    setAll('[data-hustle-earnings-month]', formatUsd(earnings));
    setAll('[data-hustle-success-rate]', successRate);
    setAll('[data-hustle-recent-settled]', String(recentCount));
    setAll('[data-hustle-latest-proof]', latestProof);

    if (activeCount > 0) {
      setAll('[data-hustle-active-note]', activeCount + ' side hustles are currently executing.');
    } else {
      setAll('[data-hustle-active-note]', 'No side hustle is running yet.');
    }
  }

  function bindSideHustleAction() {
    if (!startDemoHustleButton) {
      return;
    }
    startDemoHustleButton.addEventListener('click', async function () {
      setAll('[data-hustle-action-status]', 'Requesting budget and court clearance...');
      startDemoHustleButton.disabled = true;
      try {
        var response = await fetch('/api/agent/hustle', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: 'side_hustle_worker',
            task_description: 'Write promotional copy for open source deployment',
            amount_usd: 15.00,
            estimated_cost_usd: 0.10,
            proof_receipt: 'poge_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10),
            assigned_by: 'dashboard_operator',
            settled_by: 'dashboard_operator'
          })
        });
        var data = await response.json();
        if (!response.ok) {
          setAll('[data-hustle-action-status]', 'Failed: ' + (data.error || 'HTTP ' + response.status));
        } else if (data.status === 'blocked') {
          setAll('[data-hustle-action-status]', 'Governance Blocked: ' + (data.reason || 'Court or budget restriction.'));
        } else if (data.status === 'execution_failed') {
          setAll('[data-hustle-action-status]', 'Execution failed: ' + (data.reason || 'brain_router could not complete the task.'));
        } else {
          var earned = data.split ? '$' + (data.split.worker_usd || data.split.total_usd || '15.00') : '$15.00';
          setAll('[data-hustle-action-status]', 'Settled! Earned ' + earned + '. Settlement: ' + (data.settlement_id || 'n/a') + ' · Proof: ' + (data.memory_hash || 'n/a').slice(0, 12) + '…');
          refreshLivingInstitutionSurface();
        }
      } catch (err) {
        setAll('[data-hustle-action-status]', 'Error: ' + err.message);
      } finally {
        startDemoHustleButton.disabled = false;
      }
    });
  }

  function renderCommonwealthPanel(statusPayload, moatLockPayload) {
    if (!hasCommonwealthPanel) {
      return;
    }

    var commonwealth = statusPayload && statusPayload.commonwealth ? statusPayload.commonwealth : {};
    var federation = commonwealth && commonwealth.federation ? commonwealth.federation : {};
    var settlement = commonwealth && commonwealth.settlement ? commonwealth.settlement : {};
    var openArtifacts = toArray(moatLockPayload && moatLockPayload.open);
    var patentCandidates = toArray(moatLockPayload && moatLockPayload.patent_candidate);

    setAll('[data-cw-peer-count]', String(safeNumber(federation.peer_count)));
    setAll(
      '[data-cw-federation-note]',
      (federation.enabled ? 'federation enabled' : 'federation disabled') + ' · last sync ' + firstNonEmpty([federation.last_sync_ms], 'n/a')
    );
    setAll('[data-cw-settlement-pending]', String(safeNumber(settlement.pending_count)));
    setAll('[data-cw-settlement-settled]', String(safeNumber(settlement.settled_count)));
    setAll('[data-cw-open-artifacts]', String(openArtifacts.length));

    var openList = document.querySelector('[data-cw-open-list]');
    if (openList) {
      openList.innerHTML = openArtifacts.length
        ? openArtifacts.map(function (item) {
            return '<li><strong>' + escapeHtml(firstNonEmpty([item.category], 'open')) + '</strong> — ' +
              escapeHtml(firstNonEmpty([item.description], '')) + '</li>';
          }).join('')
        : '<li>No open artifacts reported.</li>';
    }

    var patentList = document.querySelector('[data-cw-patent-list]');
    if (patentList) {
      patentList.innerHTML = patentCandidates.length
        ? patentCandidates.map(function (item) {
            return '<li><strong>' + escapeHtml(firstNonEmpty([item.topic], 'candidate')) + '</strong> — ' +
              escapeHtml(firstNonEmpty([item.status], 'investigation')) + '</li>';
          }).join('')
        : '<li>No patent-candidate artifacts reported.</li>';
    }

    setAll(
      '[data-cw-boundary-policy]',
      firstNonEmpty([moatLockPayload && moatLockPayload.boundary_policy], 'Boundary policy unavailable.')
    );
  }

  function setPublicDirectoryStatus(message) {
    setAll('[data-public-directory-updated-at]', message);
  }

  if (!isPublicHomepage) {
    bindSideHustleAction();
  }

  /* ── Institution Browser: public-only directory ─────────────────────── */
  function renderInstitutionCard(inst, showRole) {
    var planColors = { free: '#888', starter: '#4CAF50', pro: '#2196F3', enterprise: '#FF9800' };
    var planColor = planColors[inst.plan] || '#888';
    var roleTag = showRole && inst.role ? '<span style="display:inline-block;padding:2px 8px;background:rgba(76,175,80,0.2);border-radius:3px;font-size:0.75rem;color:#4CAF50;">' + inst.role + '</span>' : '';
    return '<div style="padding:1rem;background:rgba(255,255,255,0.05);border-radius:8px;border:1px solid rgba(255,255,255,0.1);">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">' +
        '<strong style="font-size:1rem;">' + (inst.name || 'Unnamed') + '</strong>' +
        roleTag +
      '</div>' +
      '<div style="display:flex;gap:0.75rem;font-size:0.8rem;opacity:0.7;">' +
        '<span style="color:' + planColor + ';">' + (inst.plan || 'free') + '</span>' +
        '<span>' + (inst.member_count || 0) + ' members</span>' +
        '<span>' + (inst.lifecycle_state || 'active') + '</span>' +
      '</div>' +
      '<div style="margin-top:0.5rem;font-size:0.75rem;opacity:0.5;">/' + (inst.slug || inst.id || '') + '</div>' +
    '</div>';
  }

  function loadInstitutionBrowser() {
    var publicList = document.getElementById('public-institutions-list');
    if (!publicList) {
      return;
    }

    window.__meridianFetchJsonWithTimeout('/api/institutions/public', 8000)
      .then(function (data) {
        var publicItems = data.institutions || [];
        if (publicItems.length === 0) {
          publicList.innerHTML = '<p style="opacity:0.6;grid-column:1/-1;">No public institutions shared yet.</p>';
        } else {
          publicList.innerHTML = publicItems.map(function (inst) { return renderInstitutionCard(inst, false); }).join('');
        }
        setPublicDirectoryStatus('Public directory updated ' + new Date().toLocaleString() + '. Personal memberships require explicit sign-in.');
      })
      .catch(function (error) {
        publicList.innerHTML = '<p style="opacity:0.6;grid-column:1/-1;">Could not load public institutions.</p>';
        setPublicDirectoryStatus('Public directory unavailable: ' + String(error && error.message || 'unknown_error'));
      });
  }

  if (!isPublicHomepage) {
    loadInstitutionBrowser();
  }

  /* ── Federated Proof Marketplace ──────────────────────────────── */
  function loadFederatedCatalog() {
    var listEl = document.getElementById('federated-catalog-list');
    var countEl = document.querySelector('[data-fed-offering-count]');
    var priceEl = document.querySelector('[data-fed-avg-price]');
    var instEl = document.querySelector('[data-fed-inst-count]');
    if (!listEl && !countEl && !priceEl && !instEl) {
      return;
    }

    window.__meridianFetchJsonWithTimeout('/api/federation/marketplace/catalog', 8000)
      .then(function (data) {
        var offerings = data.offerings || [];
        if (countEl) { countEl.textContent = offerings.length; }
        if (offerings.length > 0) {
          var totalPrice = offerings.reduce(function (sum, o) { return sum + (o.price_usd_per_run || 0); }, 0);
          if (priceEl) { priceEl.textContent = '$' + (totalPrice / offerings.length).toFixed(2); }
          var uniqueInsts = new Set(offerings.map(function (o) { return o.org_id; }));
          if (instEl) { instEl.textContent = uniqueInsts.size; }
        }
        if (listEl) {
          if (offerings.length === 0) {
            listEl.innerHTML = '<p style="opacity:0.6;grid-column:1/-1;">No federated offerings yet. Publish agent capabilities to get started.</p>';
          } else {
            listEl.innerHTML = offerings.map(function (o) {
              return '<div style="padding:1rem;background:rgba(255,255,255,0.05);border-radius:8px;border:1px solid rgba(255,255,255,0.1);">' +
                '<strong>' + (o.capability || 'Unnamed') + '</strong>' +
                '<div style="font-size:0.85rem;margin-top:0.5rem;opacity:0.8;">' + (o.description || '') + '</div>' +
                '<div style="display:flex;gap:1rem;margin-top:0.5rem;font-size:0.8rem;">' +
                  '<span style="color:#4CAF50;">$' + (o.price_usd_per_run || 0).toFixed(2) + '/run</span>' +
                  '<span style="opacity:0.6;">' + (o.institution_name || o.org_id || '') + '</span>' +
                '</div>' +
              '</div>';
            }).join('');
          }
        }
      })
      .catch(function () {
        if (listEl) {
          listEl.innerHTML = '<p style="opacity:0.6;grid-column:1/-1;">Could not load federated catalog.</p>';
        }
      });
  }

  if (!isPublicHomepage) {
    loadFederatedCatalog();
  }
})();
