export function isImageFile(file) {
  return file.type.startsWith("image/");
}

export function parseUnifiedDiff(diffText) {
  if (!diffText) return [];
  return diffText
    .split("\n")
    .filter(
      (line) =>
        !/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity index|rename (from|to)|\\ No newline)/.test(
          line,
        ),
    )
    .map((line) => {
      if (line.startsWith("@@")) {
        return { type: "hunk", content: line };
      } else if (line.startsWith("+")) {
        return { type: "added", content: line.slice(1) };
      } else if (line.startsWith("-")) {
        return { type: "removed", content: line.slice(1) };
      } else {
        return { type: "context", content: line.slice(1) };
      }
    });
}

export function formatFileSize(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function getToastOptions(description, title, severity) {
  return {
    summary: title,
    detail: description,
    severity: severity,
    closable: false,
    life: 5000,
  };
}

export function setDarkThemeOn(save = true) {
  document.body.classList.add("dark");
  if (save) localStorage.setItem("darkTheme", "true");
}

export function setDarkThemeOff(save = true) {
  document.body.classList.remove("dark");
  if (save) localStorage.setItem("darkTheme", "false");
}

export function toggleTheme() {
  document.body.classList.contains("dark")
    ? setDarkThemeOff()
    : setDarkThemeOn();
}

export function loadTheme() {
  const storedTheme = localStorage.getItem("darkTheme");
  if (storedTheme === "true") {
    setDarkThemeOn();
  } else if (
    storedTheme === null &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    setDarkThemeOn(false);
  }
}
