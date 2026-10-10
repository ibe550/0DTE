// ─────────────────────────────────────────────────────────────
// 0DTE 대시보드 액세스 보안 제어 모듈
// ─────────────────────────────────────────────────────────────
const MY_APP_PASSWORD = "Apple"; // <- 여기에 사용할 비밀번호를 설정하세요
const AUTH_STORAGE_KEY = "0dte_auth_token";

// SHA-256 해시 함수 (브라우저 내장 Web Crypto API)
async function hashString(str) {
    const enc = new TextEncoder().encode(str);
    const buf = await crypto.subtle.digest("SHA-256", enc);
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// 인증 확인 및 대시보드 활성화
async function checkAuth() {
    const overlay = document.getElementById("auth-overlay");
    if (!overlay) return;

    const savedHash = localStorage.getItem(AUTH_STORAGE_KEY);
    const targetHash = await hashString(MY_APP_PASSWORD);

    if (savedHash === targetHash) {
        // 이미 인증된 기기: 즉시 화면 해제 및 데이터 수신 시작
        overlay.classList.add("hidden");
        window.__AUTH_VERIFIED__ = true;
        if (typeof window.startAppPolling === "function") {
            window.startAppPolling();
        }
    } else {
        // 미인증 상태: 화면 차단 유지 및 포커스
        overlay.classList.remove("hidden");
        window.__AUTH_VERIFIED__ = false;
        const input = document.getElementById("auth-input");
        if (input) input.focus();
    }
}

// 비밀번호 제출 처리
async function handleAuthSubmit(e) {
    e.preventDefault();
    const input = document.getElementById("auth-input");
    const err = document.getElementById("auth-error");
    const overlay = document.getElementById("auth-overlay");

    if (!input || !err || !overlay) return;

    const inputVal = input.value.trim();
    const inputHash = await hashString(inputVal);
    const targetHash = await hashString(MY_APP_PASSWORD);

    if (inputHash === targetHash) {
        localStorage.setItem(AUTH_STORAGE_KEY, inputHash);
        err.classList.add("hidden");
        overlay.classList.add("hidden");
        window.__AUTH_VERIFIED__ = true;
        
        // 메인 데이터 풀링 즉시 구동
        if (typeof window.startAppPolling === "function") {
            window.startAppPolling();
        } else if (typeof fetchMarketData === "function") {
            fetchMarketData();
        }
    } else {
        err.classList.remove("hidden");
        input.value = "";
        input.focus();
    }
}

// 문서 로드 시 즉시 보안 검사 실행
document.addEventListener("DOMContentLoaded", checkAuth);
