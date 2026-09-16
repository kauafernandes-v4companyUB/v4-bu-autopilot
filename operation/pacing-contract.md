# Pacing contract

`pacing.status` is `NOT_CONFIGURED` unless an approved pacing model explicitly
defines the calendar, allocation curve, metric, source and thresholds. The
engine may retain an explicitly supplied `pacing_percent`, but never assumes a
linear distribution or concludes that media is late/on-track from spend alone.
