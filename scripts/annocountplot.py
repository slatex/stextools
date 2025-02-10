from collections import defaultdict
from datetime import datetime
from fnmatch import fnmatch

from matplotlib import pyplot as plt

from annocounthistory2 import CommitInfo, load_history

HISTORY_DATA = load_history()


SINCE = datetime(2015, 1, 1)


FILTERED_DATA = [
    record for record in HISTORY_DATA.values()
    if record.date_as_datetime().timestamp() > SINCE.timestamp()
]


def accumulate(data: list[CommitInfo]) -> tuple[list[float], list[int]]:
    dates = []
    counts = []
    counts_by_repo = defaultdict(int)
    for record in sorted(data, key=lambda x: x.date_as_datetime().timestamp()):
        dates.append(record.date_as_datetime().timestamp())
        counts_by_repo[record.repo] = record.anno_count
        counts.append(sum(counts_by_repo.values()))

    return dates, counts


def plot_cumulative(data: list[CommitInfo], label: str):
    dates, counts = accumulate(data)
    plt.plot(dates, counts, label=label)


def filtered(*pattern: str) -> list[CommitInfo]:
    return [record for record in FILTERED_DATA if any(fnmatch(record.repo, p) for p in pattern)]


def plot_diff(data: list[CommitInfo], label: str):
    dates, counts = accumulate(data)

    diff_dates = []
    diff_counts = []

    for i in range(int(SINCE.timestamp()), int(datetime.now().timestamp()), 1 * 24 * 60 * 60):
        a = i - 28 * 24 * 60 * 60
        b = i

        count_before_week = 0
        count_end_of_week = 0
        for d, c in zip(dates, counts):
            if d < a:
                count_before_week = c
            if d < b:
                count_end_of_week = c

        diff_dates.append((a + b) / 2)
        diff_counts.append(count_end_of_week - count_before_week)

    plt.plot(diff_dates, diff_counts, label=label)


def cumulative_plots():
    plot_cumulative(filtered('smglom/*'), 'smglom')
    plot_cumulative(filtered('courses/*/course'), 'course')
    plot_cumulative(filtered('*/problems'), 'problems')
    # plot_cumulative(filtered('smglom/*', 'courses/*/course', '*/problems'), 'annotations')


def diff_plots():
    plot_diff(filtered('smglom/*'), 'smglom')
    plot_diff(filtered('courses/*/course'), 'course')
    plot_diff(filtered('*/problems'), 'problems')


def main():
    cumulative_plots()
    # diff_plots()
    plt.legend()

    s = SINCE
    ticks = []
    labels = []
    now = datetime.now()
    for year in range(s.year, now.year + 1):
        for month in range(1, 13):
            if year == s.year and month < s.month:
                continue
            if year == now.year and month > now.month:
                continue
            ticks.append(datetime(year, month, 1).timestamp())
            labels.append(f'{year}-{month:02d}')
    plt.xticks(ticks, labels, rotation=90)
    plt.show()


if __name__ == '__main__':
    main()
