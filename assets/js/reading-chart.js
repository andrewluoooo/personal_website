(function () {
  const scriptEl = document.currentScript;
  const readingUrl =
    (scriptEl && scriptEl.getAttribute("data-reading-url")) ||
    "/data/reading.json";

  const FINISHED_TAG = "finished";
  const monthPositions = {};
  const MONTHS = {
    jan: 1,
    january: 1,
    feb: 2,
    february: 2,
    mar: 3,
    march: 3,
    apr: 4,
    april: 4,
    may: 5,
    jun: 6,
    june: 6,
    jul: 7,
    july: 7,
    aug: 8,
    august: 8,
    sep: 9,
    sept: 9,
    september: 9,
    oct: 10,
    october: 10,
    nov: 11,
    november: 11,
    dec: 12,
    december: 12,
  };

  function chartColors() {
    const dark = document.documentElement.classList.contains("dark");
    return {
      border: dark ? "rgba(245, 245, 245, 0.85)" : "rgba(0, 0, 0, 0.8)",
      fill: dark ? "rgba(245, 245, 245, 0.08)" : "rgba(0, 0, 0, 0.05)",
      grid: dark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.05)",
      tick: dark ? "rgba(212, 212, 212, 0.85)" : "rgba(64, 64, 64, 0.9)",
      tooltipBg: dark ? "rgba(23, 23, 23, 0.92)" : "rgba(0, 0, 0, 0.8)",
      crosshair: dark ? "rgba(255, 255, 255, 0.2)" : "rgba(0, 0, 0, 0.15)",
    };
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function monthKeyFromDate(date) {
    return (
      date.getFullYear() +
      "-" +
      String(date.getMonth() + 1).padStart(2, "0")
    );
  }

  function parseCompletionDate(tags) {
    if (!Array.isArray(tags)) return null;
    for (const raw of tags) {
      const tag = String(raw || "").trim();
      if (!tag || tag.toLowerCase() === FINISHED_TAG) continue;

      let m = tag.match(/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$/);
      if (m) {
        const year = Number(m[1]);
        const month = Number(m[2]);
        if (month >= 1 && month <= 12) {
          return `${year}-${String(month).padStart(2, "0")}-01`;
        }
      }

      m = tag.match(/^(\d{1,2})[/-](\d{4})$/);
      if (m) {
        const month = Number(m[1]);
        const year = Number(m[2]);
        if (month >= 1 && month <= 12) {
          return `${year}-${String(month).padStart(2, "0")}-01`;
        }
      }

      m = tag.match(/^([A-Za-z]+)\.?\s+'?(\d{2}|\d{4})$/);
      if (m) {
        const month = MONTHS[m[1].toLowerCase()];
        let year = Number(m[2]);
        if (month) {
          if (year < 100) year += 2000;
          return `${year}-${String(month).padStart(2, "0")}-01`;
        }
      }

      // july26 / Jul26 / july2026 (no space)
      m = tag.match(/^([A-Za-z]+)'?(\d{2}|\d{4})$/);
      if (m) {
        const month = MONTHS[m[1].toLowerCase()];
        let year = Number(m[2]);
        if (month) {
          if (year < 100) year += 2000;
          return `${year}-${String(month).padStart(2, "0")}-01`;
        }
      }
    }
    return null;
  }

  function normalizeBooks(rawBooks) {
    return (rawBooks || [])
      .map((book) => {
        const tags = Array.isArray(book.tags) ? book.tags : [];
        const isFinished =
          tags.some((tag) => String(tag).toLowerCase() === FINISHED_TAG) ||
          // Synced payload already filtered to finished books.
          (!tags.length && Boolean(book.date));
        if (!isFinished) return null;

        const date = parseCompletionDate(tags) || book.date;
        if (!date) return null;
        return { ...book, date, tags };
      })
      .filter(Boolean)
      .sort((a, b) => a.date.localeCompare(b.date));
  }

  function showEmptyState(message) {
    const countEl = document.getElementById("reading-book-count");
    if (countEl) countEl.textContent = "0";

    const booksContainer = document.getElementById("books-list");
    if (booksContainer) {
      booksContainer.innerHTML = `<p class="reading-empty">${escapeHtml(message)}</p>`;
    }

    const canvas = document.getElementById("readingChart");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function displayBooks(books) {
    const booksContainer = document.getElementById("books-list");
    if (!booksContainer) return;

    const booksByMonth = {};
    books.forEach((book, index) => {
      const date = new Date(book.date + "T00:00:00");
      const key = monthKeyFromDate(date);
      if (!booksByMonth[key]) booksByMonth[key] = [];
      booksByMonth[key].push({ ...book, index });
    });

    const sortedMonths = Object.keys(booksByMonth).sort();
    let html =
      '<div class="books-carousel" id="booksCarousel"><div class="carousel-content">';

    sortedMonths.forEach((key) => {
      const [year, month] = key.split("-");
      const label = new Date(Number(year), Number(month) - 1, 1).toLocaleDateString(
        "en-US",
        { month: "short", year: "2-digit" }
      );

      html += `<div class="month-section" data-month="${escapeHtml(key)}">
        <div class="month-header">${escapeHtml(label)}</div>
        <div class="month-books">`;

      booksByMonth[key].forEach((book) => {
        const title = book.title || "Untitled";
        const author = book.author || "";
        const cover = book.cover || "";
        html += `<div class="book-card" data-index="${book.index}" title="${escapeHtml(title)}${author ? " — " + escapeHtml(author) : ""}">
          <div class="book-cover">
            ${
              cover
                ? `<img class="book-img" src="${escapeHtml(cover)}" alt="${escapeHtml(title)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">`
                : `<div class="book-cover-fallback" aria-hidden="true">${escapeHtml(title.charAt(0) || "?")}</div>`
            }
          </div>
          <div class="book-title">${escapeHtml(title)}</div>
          ${author ? `<div class="book-author">${escapeHtml(author)}</div>` : ""}
        </div>`;
      });

      html += "</div></div>";
    });

    html += "</div></div>";
    booksContainer.innerHTML = html;

    Object.keys(monthPositions).forEach((key) => delete monthPositions[key]);
    booksContainer.querySelectorAll(".month-section").forEach((section) => {
      const key = section.getAttribute("data-month");
      monthPositions[key] = section.offsetLeft;
    });
  }

  function scrollCarouselToMonth(monthKey) {
    const carousel = document.getElementById("booksCarousel");
    if (!carousel || monthPositions[monthKey] == null) return;
    carousel.scrollLeft = monthPositions[monthKey];
  }

  async function boot() {
    const canvas = document.getElementById("readingChart");
    if (!canvas || typeof Chart === "undefined") return;

    let books = [];
    try {
      const response = await fetch(readingUrl);
      if (!response.ok) throw new Error("Failed to fetch reading data");
      const payload = await response.json();
      books = normalizeBooks(payload.books);
    } catch (err) {
      console.error("Unable to load reading data", err);
      showEmptyState("Unable to load reading data.");
      return;
    }

    if (!books.length) {
      showEmptyState(
        'No finished books yet. Tag books “finished” plus a month/year tag (e.g. “Jul 26”) in Notion, then re-sync.'
      );
      return;
    }

    const countEl = document.getElementById("reading-book-count");
    if (countEl) {
      const today = new Date();
      const oneYearAgo = new Date(today);
      oneYearAgo.setDate(oneYearAgo.getDate() - 365);
      const recent = books.filter((book) => {
        const date = new Date(book.date + "T00:00:00");
        return date >= oneYearAgo && date <= today;
      });
      countEl.textContent = String(recent.length);
    }

    displayBooks(books);

    const monthlyData = {};
    let earliestDate = null;
    let latestDate = null;

    books.forEach((book) => {
      const date = new Date(book.date + "T00:00:00");
      if (!earliestDate || date < earliestDate) earliestDate = date;
      if (!latestDate || date > latestDate) latestDate = date;
    });

    if (!earliestDate || !latestDate) return;

    const cursor = new Date(earliestDate.getFullYear(), earliestDate.getMonth(), 1);
    const end = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
    while (cursor <= end) {
      const key = monthKeyFromDate(cursor);
      monthlyData[key] = 0;
      cursor.setMonth(cursor.getMonth() + 1);
    }

    books.forEach((book) => {
      const date = new Date(book.date + "T00:00:00");
      const key = monthKeyFromDate(date);
      if (Object.prototype.hasOwnProperty.call(monthlyData, key)) {
        monthlyData[key] += 1;
      }
    });

    const monthKeys = Object.keys(monthlyData);
    const labels = monthKeys.map((key) => {
      const [year, month] = key.split("-");
      return new Date(Number(year), Number(month) - 1, 1).toLocaleDateString(
        "en-US",
        { month: "short", year: "2-digit" }
      );
    });
    const data = Object.values(monthlyData);

    const verticalLinePlugin = {
      id: "verticalLine",
      afterDatasetsDraw(chart) {
        const { ctx } = chart;
        const colors = chartColors();
        if (
          chart._lastEvent &&
          chart._lastEvent.type === "mousemove" &&
          chart._lastEvent.x >= chart.scales.x.left &&
          chart._lastEvent.x <= chart.scales.x.right
        ) {
          const x = chart._lastEvent.x;
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x, chart.scales.y.top);
          ctx.lineTo(x, chart.scales.y.bottom);
          ctx.lineWidth = 1;
          ctx.strokeStyle = colors.crosshair;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.restore();
        }
      },
      afterEvent(chart, args) {
        chart._lastEvent = args.event;
        chart.render();
      },
    };

    let chartInstance = null;

    function createChart() {
      const colors = chartColors();
      if (chartInstance) chartInstance.destroy();

      chartInstance = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: "Books finished",
              data,
              backgroundColor: colors.fill,
              borderColor: colors.border,
              borderWidth: 2,
              pointRadius: 3,
              pointBackgroundColor: colors.border,
              pointBorderColor: colors.border,
              pointHoverRadius: 5,
              tension: 0.2,
              fill: true,
            },
          ],
        },
        plugins: [verticalLinePlugin],
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            intersect: false,
            mode: "index",
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: colors.tooltipBg,
              padding: 8,
              cornerRadius: 4,
              displayColors: false,
              callbacks: {
                label(context) {
                  const n = context.parsed.y;
                  return n + (n === 1 ? " book" : " books");
                },
              },
            },
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                stepSize: 1,
                precision: 0,
                color: colors.tick,
                font: { size: 11 },
              },
              grid: {
                drawBorder: false,
                color: colors.grid,
              },
              border: { display: false },
            },
            x: {
              ticks: {
                color: colors.tick,
                font: { size: 11 },
                maxRotation: 45,
                minRotation: 0,
              },
              grid: {
                display: false,
                drawBorder: false,
              },
              border: { display: false },
            },
          },
          onHover(event, activeElements) {
            event.native.target.style.cursor =
              activeElements.length > 0 ? "pointer" : "default";
            if (activeElements.length > 0) {
              scrollCarouselToMonth(monthKeys[activeElements[0].index]);
            }
          },
        },
      });
    }

    createChart();

    window.addEventListener("load", () => {
      document.querySelectorAll(".month-section").forEach((section) => {
        const key = section.getAttribute("data-month");
        monthPositions[key] = section.offsetLeft;
      });
    });

    const observer = new MutationObserver(() => createChart());
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  boot();
})();
