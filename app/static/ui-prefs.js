(function () {
  const KEY_LANG = "ghv.ui.lang";
  const KEY_THEME = "ghv.ui.theme";
  const LANGS = new Set(["ko", "en"]);
  const THEMES = new Set(["light", "dark"]);
  const listeners = new Set();

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_) {
      // Ignore storage errors in private mode or blocked environments.
    }
  }

  function detectLanguage() {
    const nav = (navigator.language || "en").toLowerCase();
    return nav.startsWith("ko") ? "ko" : "en";
  }

  function detectTheme() {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
    return "light";
  }

  function normalizeLanguage(value) {
    return LANGS.has(value) ? value : detectLanguage();
  }

  function normalizeTheme(value) {
    return THEMES.has(value) ? value : detectTheme();
  }

  const state = {
    language: normalizeLanguage(readStorage(KEY_LANG)),
    theme: normalizeTheme(readStorage(KEY_THEME)),
  };

  function applyLanguage(language) {
    document.documentElement.lang = language;
    document.documentElement.setAttribute("data-lang", language);
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function notify() {
    const snapshot = { ...state };
    listeners.forEach((fn) => {
      try {
        fn(snapshot);
      } catch (_) {
        // Ignore listener errors to avoid breaking preference updates.
      }
    });
  }

  function setLanguage(language) {
    state.language = normalizeLanguage(language);
    writeStorage(KEY_LANG, state.language);
    applyLanguage(state.language);
    notify();
  }

  function setTheme(theme) {
    state.theme = normalizeTheme(theme);
    writeStorage(KEY_THEME, state.theme);
    applyTheme(state.theme);
    notify();
  }

  function bindSelectors(options) {
    const langSelector = document.getElementById(options.languageSelectorId);
    const themeSelector = document.getElementById(options.themeSelectorId);

    if (langSelector) {
      langSelector.value = state.language;
      langSelector.addEventListener("change", () => setLanguage(langSelector.value));
    }
    if (themeSelector) {
      themeSelector.value = state.theme;
      themeSelector.addEventListener("change", () => setTheme(themeSelector.value));
    }
  }

  function onChange(handler) {
    listeners.add(handler);
    handler({ ...state });
    return () => listeners.delete(handler);
  }

  applyLanguage(state.language);
  applyTheme(state.theme);

  window.UI_PREFS = {
    getLanguage: () => state.language,
    getTheme: () => state.theme,
    setLanguage,
    setTheme,
    bindSelectors,
    onChange,
  };
})();
