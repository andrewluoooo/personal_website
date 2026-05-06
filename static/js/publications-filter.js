(function () {
	const root = document.getElementById("publications-root");
	if (!root) return;

	const chips = root.querySelectorAll(".pub-filter-chip");
	const blocks = root.querySelectorAll(".pub-year-block");

	function activeFilters() {
		return Array.from(chips)
			.filter((c) => c.classList.contains("pub-filter-chip--active"))
			.map((c) => c.getAttribute("data-filter"))
			.filter(Boolean);
	}

	function cardMatches(card, filters) {
		const raw = card.getAttribute("data-tags") || "";
		const tags = raw.split(/\s+/).filter(Boolean);
		return filters.some((f) => tags.includes(f));
	}

	function update() {
		const filters = activeFilters();
		const showAll = filters.length === 0;

		root.querySelectorAll(".pub-card").forEach((card) => {
			const show = showAll || cardMatches(card, filters);
			card.hidden = !show;
		});

		blocks.forEach((block) => {
			const visible = Array.from(block.querySelectorAll(".pub-card")).some((c) => !c.hidden);
			block.hidden = !visible;
		});
	}

	chips.forEach((chip) => {
		chip.addEventListener("click", () => {
			chip.classList.toggle("pub-filter-chip--active");
			const on = chip.classList.contains("pub-filter-chip--active");
			chip.setAttribute("aria-pressed", on ? "true" : "false");
			update();
		});
	});

	chips.forEach((chip) => {
		const on = chip.classList.contains("pub-filter-chip--active");
		chip.setAttribute("aria-pressed", on ? "true" : "false");
	});

	update();
})();
