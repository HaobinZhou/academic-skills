"""Apply a signal on the next bar to prevent look-ahead."""


def execution_bar(signal_bar: int) -> int:
    return signal_bar + 1
