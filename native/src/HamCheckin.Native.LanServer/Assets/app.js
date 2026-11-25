'use strict';

// 手机页只做同源 /api 调用与状态展示：解析、去重、入库都在电脑端（设计文档 6.1 / 6.3）。
(() => {
  const TOKEN_KEY = 'hamcheckin.lan.token';
  const PIN_LENGTH = 6;
  const POLL_INTERVAL_MS = 1500;
  const MAX_RETRY_MS = 15000;
  const VIEW_NAMES = ['pair', 'input', 'waiting', 'approved', 'rejected'];
  const SESSION_STATUS_TEXT = { active: '点名进行中', ended: '本场已结束', none: '无场次' };
  const SESSION_ENDED_TEXT = '本场已结束，请找主持人。';
  const OFFLINE_TEXT = '与电脑断开，请让主持人重新启动收件服务。';

  class ApiError extends Error {
    constructor(code, status, message, retryAfterSeconds) {
      super(message);
      this.name = 'ApiError';
      this.code = code;
      this.status = status;
      this.retryAfterSeconds = retryAfterSeconds || 0;
    }
  }

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || '',
    view: 'pair',
    sessionActive: false,
    canSubmit: false,
    pendingId: '',
    pendingRaw: '',
    pollTimer: 0,
    pollFailures: 0,
    elapsedTimer: 0,
    submittedAt: 0,
  };

  const dom = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function show(el) {
    el.hidden = false;
  }

  function hide(el) {
    el.hidden = true;
    el.textContent = '';
  }

  function showError(el, text) {
    el.textContent = text;
    el.hidden = false;
  }

  function setBanner(text) {
    if (text) {
      dom.banner.textContent = text;
      dom.banner.hidden = false;
    } else {
      hide(dom.banner);
    }
  }

  async function api(path, options) {
    const request = options || {};
    const headers = {};
    if (request.body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    if (state.token) {
      headers.Authorization = 'Bearer ' + state.token;
    }

    let response;
    try {
      response = await fetch(path, {
        method: request.method || 'GET',
        headers,
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
        cache: 'no-store',
      });
    } catch (error) {
      throw new ApiError('offline', 0, OFFLINE_TEXT, 0);
    }

    const retryAfter = Number(response.headers.get('Retry-After')) || 0;
    let payload = null;
    if ((response.headers.get('Content-Type') || '').includes('application/json')) {
      try {
        payload = await response.json();
      } catch (error) {
        payload = null;
      }
    }

    if (response.ok) {
      return payload;
    }

    const code = payload && typeof payload.error === 'string' ? payload.error : 'request_failed';
    const message = payload && typeof payload.message === 'string' ? payload.message : '请求失败。';
    throw new ApiError(code, response.status, message, retryAfter);
  }

  function showView(name) {
    state.view = name;
    for (const view of VIEW_NAMES) {
      byId('view-' + view).hidden = view !== name;
    }
    if (name !== 'waiting') {
      stopPolling();
      stopElapsed();
    }
  }

  function storeToken(token) {
    state.token = token;
    localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    state.token = '';
    localStorage.removeItem(TOKEN_KEY);
  }

  function resetPending() {
    // 只结束本次轮询与计时；pendingRaw 必须保留，供「返回修改」、
    // 过期/拒绝页以及 401 重新配对后恢复原始草稿。
    state.pendingId = '';
    stopPolling();
    stopElapsed();
  }

  function resetPreview() {
    state.canSubmit = false;
    hide(dom.previewCard);
    hide(dom.previewError);
    dom.previewFields.replaceChildren();
  }

  function updateSubmitState() {
    dom.submitButton.disabled = !state.canSubmit || !state.sessionActive;
  }

  function renderHealth(health) {
    dom.pcName.textContent = health.pcName || '';
    dom.sessionName.textContent = health.sessionName || '未开播';
    dom.sessionStatus.textContent = SESSION_STATUS_TEXT[health.sessionStatus] || health.sessionStatus || '';
    dom.sessionStatus.classList.toggle('ended', health.sessionStatus !== 'active');
    state.sessionActive = health.sessionStatus === 'active';
    updateSubmitState();
  }

  async function loadHealth() {
    const health = await api('/api/health');
    renderHealth(health);
  }

  function handleTokenInvalid() {
    clearToken();
    resetPending();
    resetPreview();
    setBanner('与电脑的连接已失效，请重新输入 PIN。');
    dom.pin.value = '';
    showView('pair');
    dom.pin.focus();
  }

  async function onPairSubmit(event) {
    event.preventDefault();
    const pin = dom.pin.value.trim();
    if (pin.length !== PIN_LENGTH || !/^\d+$/.test(pin)) {
      showError(dom.pairError, '请输入 6 位数字 PIN。');
      return;
    }

    dom.pairButton.disabled = true;
    dom.pairButton.textContent = '连接中…';
    hide(dom.pairError);
    try {
      const paired = await api('/api/pair', {
        method: 'POST',
        body: { pin: pin, deviceLabel: dom.deviceLabel.value.trim() },
      });
      storeToken(paired.token);
      setBanner('');
      resetPending();
      resetPreview();
      // 401 后重新配对：把上次提交/未发出的原文放回输入框，不丢草稿。
      if (state.pendingRaw) {
        dom.draft.value = state.pendingRaw;
      }
      await loadHealth();
      showView('input');
      dom.draft.focus();
    } catch (error) {
      if (error.code === 'bad_pin') {
        showError(dom.pairError, 'PIN 不正确。');
      } else if (error.code === 'rate_limited') {
        showError(dom.pairError, '尝试太频繁，请 ' + Math.max(1, error.retryAfterSeconds) + ' 秒后再试。');
      } else if (error.code === 'offline') {
        showError(dom.pairError, '无法连接电脑，请确认电脑上的收件服务已启动。');
      } else {
        showError(dom.pairError, error.message);
      }
    } finally {
      dom.pairButton.disabled = false;
      dom.pairButton.textContent = '连接';
    }
  }

  function renderPreview(preview) {
    const fields = [
      ['呼号', preview.callsign],
      ['QTH', preview.qth],
      ['设备', preview.device],
      ['天线', preview.antenna],
      ['功率', preview.power],
      ['信号', preview.signal],
    ];
    const fragment = document.createDocumentFragment();
    for (const [label, value] of fields) {
      const term = document.createElement('dt');
      term.textContent = label;
      const description = document.createElement('dd');
      description.textContent = value || '—';
      fragment.append(term, description);
    }
    dom.previewFields.replaceChildren(fragment);

    const unmatched = Array.isArray(preview.unmatched) ? preview.unmatched : [];
    if (unmatched.length > 0) {
      dom.previewUnmatched.textContent = '未识别：' + unmatched.join(' ');
      show(dom.previewUnmatched);
    } else {
      hide(dom.previewUnmatched);
    }

    state.canSubmit = preview.canSubmit === true;
    updateSubmitState();
    show(dom.previewCard);
    if (!state.canSubmit) {
      showError(dom.previewError, '没识别到呼号，请补充后重新预览。');
    } else if (!state.sessionActive) {
      showError(dom.previewError, SESSION_ENDED_TEXT);
    } else {
      hide(dom.previewError);
    }
  }

  async function onPreview() {
    const text = dom.draft.value.trim();
    if (!text) {
      showError(dom.inputError, '请输入点名原文。');
      return;
    }

    dom.previewButton.disabled = true;
    dom.previewButton.textContent = '解析中…';
    hide(dom.inputError);
    try {
      const preview = await api('/api/preview', { method: 'POST', body: { text: text } });
      renderPreview(preview);
    } catch (error) {
      if (error.code === 'token_invalid') {
        handleTokenInvalid();
        return;
      }
      if (error.code === 'rate_limited') {
        showError(dom.inputError, '操作太快，请 ' + Math.max(1, error.retryAfterSeconds) + ' 秒后再试。');
      } else if (error.code === 'offline') {
        showError(dom.inputError, OFFLINE_TEXT);
      } else {
        showError(dom.inputError, error.message);
      }
    } finally {
      dom.previewButton.disabled = false;
      dom.previewButton.textContent = '预览';
    }
  }

  function newSubmissionId() {
    const bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
      window.crypto.getRandomValues(bytes);
      return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
    }
    return 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  async function onSubmit() {
    const text = dom.draft.value.trim();
    if (!text) {
      showError(dom.inputError, '请输入点名原文。');
      return;
    }

    if (!state.pendingId) {
      state.pendingId = newSubmissionId();
    }

    dom.submitButton.disabled = true;
    dom.submitButton.textContent = '提交中…';
    hide(dom.previewError);
    try {
      await api('/api/submissions', {
        method: 'POST',
        body: { clientSubmissionId: state.pendingId, rawText: text },
      });
      enterWaiting(text);
    } catch (error) {
      if (error.code === 'token_invalid') {
        handleTokenInvalid();
        return;
      }
      if (error.code === 'no_callsign') {
        showError(dom.previewError, '没识别到呼号，请补充。');
      } else if (error.code === 'session_ended') {
        state.sessionActive = false;
        dom.sessionStatus.classList.add('ended');
        showError(dom.previewError, SESSION_ENDED_TEXT);
      } else if (error.code === 'queue_full') {
        showError(dom.previewError, '主持人还没处理完，请稍后再试。');
      } else if (error.code === 'rate_limited') {
        showError(dom.previewError, '操作太快，请 ' + Math.max(1, error.retryAfterSeconds) + ' 秒后再试。');
      } else if (error.code === 'offline') {
        showError(dom.previewError, OFFLINE_TEXT);
      } else {
        showError(dom.previewError, error.message);
      }
    } finally {
      dom.submitButton.textContent = '提交给主持人';
      updateSubmitState();
    }
  }

  function formatTime(isoText) {
    const moment = new Date(isoText);
    if (Number.isNaN(moment.getTime())) {
      return '';
    }
    return [moment.getHours(), moment.getMinutes(), moment.getSeconds()]
      .map((value) => String(value).padStart(2, '0'))
      .join(':');
  }

  function enterWaiting(rawText) {
    state.pendingRaw = rawText;
    state.submittedAt = Date.now();
    dom.waitingRaw.textContent = rawText;
    hide(dom.waitingError);
    showView('waiting');
    startElapsed();
    startPolling();
  }

  function startElapsed() {
    stopElapsed();
    renderElapsed();
    state.elapsedTimer = window.setInterval(renderElapsed, 1000);
  }

  function stopElapsed() {
    if (state.elapsedTimer) {
      window.clearInterval(state.elapsedTimer);
      state.elapsedTimer = 0;
    }
  }

  function renderElapsed() {
    const total = Math.max(0, Math.floor((Date.now() - state.submittedAt) / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    dom.waitingElapsed.textContent = minutes > 0
      ? minutes + ' 分 ' + seconds + ' 秒'
      : seconds + ' 秒';
  }

  function startPolling() {
    stopPolling();
    state.pollFailures = 0;
    schedulePoll(0);
  }

  function stopPolling() {
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = 0;
    }
  }

  function schedulePoll(delay) {
    stopPolling();
    state.pollTimer = window.setTimeout(pollOnce, delay);
  }

  async function pollOnce() {
    state.pollTimer = 0;
    if (!state.pendingId || state.view !== 'waiting') {
      return;
    }

    try {
      const status = await api('/api/submissions/' + encodeURIComponent(state.pendingId));
      state.pollFailures = 0;
      hide(dom.waitingError);
      applyStatus(status);
      if (state.view === 'waiting') {
        schedulePoll(POLL_INTERVAL_MS);
      }
    } catch (error) {
      if (error.code === 'token_invalid') {
        handleTokenInvalid();
        return;
      }
      if (error.status === 404) {
        showExpired();
        return;
      }
      if (error.code === 'rate_limited') {
        schedulePoll(Math.max(1, error.retryAfterSeconds) * 1000);
        return;
      }
      state.pollFailures += 1;
      showError(dom.waitingError, OFFLINE_TEXT + '正在重试…');
      const backoff = Math.min(POLL_INTERVAL_MS * Math.pow(2, state.pollFailures), MAX_RETRY_MS);
      schedulePoll(backoff);
    }
  }

  function applyStatus(status) {
    if (!status || typeof status.state !== 'string') {
      return;
    }
    if (status.state === 'approved') {
      const sequence = typeof status.sequenceNo === 'number' ? '第 ' + status.sequenceNo + ' 条' : '已记入本场点名';
      const time = formatTime(status.decidedAt);
      dom.approvedLine.textContent = time ? sequence + ' · ' + time : sequence;
      dom.approvedRaw.textContent = state.pendingRaw;
      resetPending();
      showView('approved');
    } else if (status.state === 'rejected') {
      const reason = typeof status.reason === 'string' && status.reason ? status.reason : '主持人未确认该条，请核对后重新提交。';
      dom.rejectedTitle.textContent = '主持人未确认';
      dom.rejectedReason.textContent = reason;
      dom.rejectedRaw.textContent = state.pendingRaw;
      resetPending();
      showView('rejected');
    } else if (status.state === 'expired') {
      showExpired();
    }
  }

  function showExpired() {
    dom.rejectedTitle.textContent = '提交已过期';
    dom.rejectedReason.textContent = '已过期，可重新提交。';
    dom.rejectedRaw.textContent = state.pendingRaw;
    resetPending();
    showView('rejected');
  }

  function backToEdit() {
    const raw = state.pendingRaw || dom.draft.value;
    resetPending();
    resetPreview();
    hide(dom.waitingError);
    dom.draft.value = raw;
    showView('input');
    dom.draft.focus();
  }

  function onNext() {
    resetPending();
    state.pendingRaw = '';
    resetPreview();
    dom.draft.value = '';
    showView('input');
    dom.draft.focus();
  }

  async function start() {
    dom.banner = byId('banner');
    dom.pcName = byId('pc-name');
    dom.pairForm = byId('pair-form');
    dom.pin = byId('pin');
    dom.deviceLabel = byId('device-label');
    dom.pairButton = byId('pair-button');
    dom.pairError = byId('pair-error');
    dom.sessionName = byId('session-name');
    dom.sessionStatus = byId('session-status');
    dom.draft = byId('draft');
    dom.previewButton = byId('preview-button');
    dom.inputError = byId('input-error');
    dom.previewCard = byId('preview-card');
    dom.previewFields = byId('preview-fields');
    dom.previewUnmatched = byId('preview-unmatched');
    dom.submitButton = byId('submit-button');
    dom.editButton = byId('edit-button');
    dom.previewError = byId('preview-error');
    dom.waitingElapsed = byId('waiting-elapsed');
    dom.waitingRaw = byId('waiting-raw');
    dom.waitingError = byId('waiting-error');
    dom.waitingBack = byId('waiting-back');
    dom.approvedLine = byId('approved-line');
    dom.approvedRaw = byId('approved-raw');
    dom.approvedNew = byId('approved-new');
    dom.rejectedTitle = byId('rejected-title');
    dom.rejectedReason = byId('rejected-reason');
    dom.rejectedRaw = byId('rejected-raw');
    dom.rejectedEdit = byId('rejected-edit');

    dom.pin.addEventListener('input', () => {
      dom.pin.value = dom.pin.value.replace(/\D/g, '').slice(0, PIN_LENGTH);
    });
    dom.pairForm.addEventListener('submit', onPairSubmit);
    dom.previewButton.addEventListener('click', onPreview);
    dom.submitButton.addEventListener('click', onSubmit);
    dom.editButton.addEventListener('click', resetPreview);
    dom.waitingBack.addEventListener('click', backToEdit);
    dom.rejectedEdit.addEventListener('click', backToEdit);
    dom.approvedNew.addEventListener('click', onNext);

    if (!state.token) {
      showView('pair');
      dom.pin.focus();
      return;
    }

    try {
      await loadHealth();
      showView('input');
      dom.draft.focus();
    } catch (error) {
      if (error.code === 'token_invalid') {
        handleTokenInvalid();
        return;
      }
      clearToken();
      setBanner('');
      showView('pair');
      showError(dom.pairError, '无法连接电脑，请让主持人启动收件服务后再连接。');
      dom.pin.focus();
    }
  }

  start();
})();
