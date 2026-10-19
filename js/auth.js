// ─────────────────────────────────────────────────────────────
// 0DTE 대시보드 서버 인증 모듈 (v2)
//  - 비밀번호는 서버(Vercel 환경변수 DASHBOARD_USERS)에만 존재, JS에 평문 없음
//  - 1인 1비밀번호 + 1비밀번호 1기기 바인딩 (서버가 강제)
//  - 로그인 성공 시 토큰을 sessionStorage에 보관, 매 API 호출에 Bearer 첨부
// ─────────────────────────────────────────────────────────────
const AUTH_TOKEN_KEY = "0dte_auth_token_v2";
const AUTH_USER_KEY = "0dte_auth_user_v2";
const DEVICE_ID_KEY = "0dte_device_id";
// AUTH_DISABLED: true면 잠금화면 없이 바로 진입 (임시 테스트용)
const AUTH_DISABLED = true;

function getDeviceId() {
    let id = null;
    try { id = localStorage.getItem(DEVICE_ID_KEY); } catch (e) {}
    if (!id) {
        id = (crypto.randomUUID ? crypto.randomUUID() : "dev-" + Date.now() + "-" + Math.random().toString(36).slice(2));
        try { localStorage.setItem(DEVICE_ID_KEY, id); } catch (e) {}
    }
    return id;
}

function authHeaders() {
    const t = window.__AUTH_TOKEN__ || null;
    return t ? { "Authorization": "Bearer " + t } : {};
}

function showAuthOverlay(msg) {
    const overlay = document.getElementById("auth-overlay");
    const err = document.getElementById("auth-error");
    if (err && msg) { err.innerText = msg; err.classList.remove("hidden"); }
    if (overlay) overlay.classList.remove("hidden");
    window.__AUTH_VERIFIED__ = false;
    window.__AUTH_TOKEN__ = null;
    try { sessionStorage.removeItem(AUTH_TOKEN_KEY); } catch (e) {}
}

function hideAuthOverlay() {
    const overlay = document.getElementById("auth-overlay");
    if (overlay) overlay.classList.add("hidden");
    window.__AUTH_VERIFIED__ = true;
}

// 인증 확인: 저장된 토큰이 있으면 폴링 시작 (유효성은 첫 호출에서 검증)
async function checkAuth() {
    if (AUTH_DISABLED) {
        hideAuthOverlay();
        if (typeof window.startAppPolling === "function") window.startAppPolling();
        return;
    }
    let token = null;
    try { token = sessionStorage.getItem(AUTH_TOKEN_KEY); } catch (e) {}
    if (token) {
        window.__AUTH_TOKEN__ = token;
        hideAuthOverlay();
        if (typeof window.startAppPolling === "function") window.startAppPolling();
        return;
    }
    showAuthOverlay();
    const input = document.getElementById("auth-user");
    if (input) input.focus();
}

// 로그아웃: 서버 바인딩 해제 + 로컬 토큰 삭제 → 잠금화면
async function doLogout() {
    const apiBase = (typeof API_URL !== "undefined" && API_URL)
        ? API_URL.replace(/\/api\/market-data.*$/, "")
        : "";
    try {
        await fetch(apiBase + "/api/logout", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
        });
    } catch (e) {}
    window.__AUTH_TOKEN__ = null;
    window.__AUTH_VERIFIED__ = false;
    try {
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
        sessionStorage.removeItem(AUTH_USER_KEY);
    } catch (e) {}
    showAuthOverlay();
}

// 만료/무효 토큰 → 잠금화면으로
function handleAuthExpired(msg) {
    showAuthOverlay(msg || "세션이 만료되었습니다. 다시 로그인하세요.");
}

// 로그인 제출 → 서버 검증
async function handleAuthSubmit(e) {
    e.preventDefault();
    const userEl = document.getElementById("auth-user");
    const input = document.getElementById("auth-input");
    const err = document.getElementById("auth-error");
    const btn = document.querySelector("#auth-form button[type=submit]");
    if (!userEl || !input) return;

    const user = userEl.value.trim();
    const pw = input.value;
    if (!user || !pw) return;

    if (err) { err.classList.add("hidden"); }
    if (btn) { btn.disabled = true; btn.innerText = "확인 중..."; }
    try {
        const apiBase = (typeof API_URL !== "undefined" && API_URL)
            ? API_URL.replace(/\/api\/market-data.*$/, "")
            : "";
        const doLoginFetch = (force) => fetch(apiBase + "/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user: user, password: pw, device_id: getDeviceId(), force: !!force }),
        });
        let res = await doLoginFetch(false);
        let data = await res.json().catch(() => ({}));
        // 기기 전환 확인
        if (!res.ok && data && data.error === "TAKEOVER_REQUIRED") {
            const msg = data.message || "다른 기기에서 사용 중입니다. 전환하시겠습니까?";
            if (confirm(msg)) {
                res = await doLoginFetch(true);
                data = await res.json().catch(() => ({}));
            } else {
                if (err) { err.innerText = "취소되었습니다."; err.classList.remove("hidden"); }
                input.value = "";
                if (btn) { btn.disabled = false; btn.innerHTML = "대시보드 잠금 해제"; }
                return;
            }
        }
        if (res.ok && data.ok && data.token) {
            window.__AUTH_TOKEN__ = data.token;
            try {
                sessionStorage.setItem(AUTH_TOKEN_KEY, data.token);
                sessionStorage.setItem(AUTH_USER_KEY, data.user || user);
            } catch (e) {}
            input.value = "";
            hideAuthOverlay();
            if (typeof window.startAppPolling === "function") {
                window.startAppPolling();
            } else if (typeof fetchMarketData === "function") {
                fetchMarketData();
            }
        } else {
            const msg = (data && data.error) || "로그인 실패";
            if (err) { err.innerText = msg; err.classList.remove("hidden"); }
            input.value = "";
            input.focus();
        }
    } catch (e) {
        if (err) { err.innerText = "서버 연결 실패"; err.classList.remove("hidden"); }
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = "대시보드 잠금 해제"; }
    }
}

// 로그아웃 (수동)
function handleLogout() {
    showAuthOverlay();
}

document.addEventListener("DOMContentLoaded", () => {
    checkAuth();
    const lb = document.getElementById("logout-btn");
    if (lb) lb.addEventListener("click", () => { if (confirm("로그아웃하시겠습니까? (다른 기기에서 로그인 가능해집니다)")) doLogout(); });
});
