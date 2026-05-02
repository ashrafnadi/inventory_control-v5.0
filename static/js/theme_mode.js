// Theme management
document.addEventListener("DOMContentLoaded", function () {
	// Get saved theme preference or default to 'system'
	const savedTheme = localStorage.getItem("theme") || "system";
	const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
		? "dark"
		: "light";
	let currentTheme = savedTheme === "system" ? systemTheme : savedTheme;

	// Apply theme
	document.documentElement.setAttribute("data-theme", currentTheme);
	updateThemeIcon(currentTheme);

	// Add event listeners to theme options
	document.querySelectorAll(".theme-option").forEach((option) => {
		option.addEventListener("click", function (e) {
			e.preventDefault();
			const selectedTheme = this.getAttribute("data-theme");
			localStorage.setItem("theme", selectedTheme);

			const systemTheme = window.matchMedia("(prefers-color-scheme: dark)")
				.matches
				? "dark"
				: "light";
			const newTheme = selectedTheme === "system" ? systemTheme : selectedTheme;

			document.documentElement.setAttribute("data-theme", newTheme);
			updateThemeIcon(newTheme);
		});
	});

	// Listen for system theme changes
	window
		.matchMedia("(prefers-color-scheme: dark)")
		.addEventListener("change", (e) => {
			if (localStorage.getItem("theme") === "system") {
				const newTheme = e.matches ? "dark" : "light";
				document.documentElement.setAttribute("data-theme", newTheme);
				updateThemeIcon(newTheme);
			}
		});

	function updateThemeIcon(theme) {
		const themeSwitcher = document.querySelector(".theme-switcher");
		if (!themeSwitcher) return;

		// Update icon
		const icon = themeSwitcher.querySelector("i");
		if (theme === "dark") {
			icon.className = "bi bi-moon me-1";
			themeSwitcher.querySelector("span").textContent = "Dark";
		} else {
			icon.className = "bi bi-brightness-high me-1";
			themeSwitcher.querySelector("span").textContent = "Light";
		}
	}
});
