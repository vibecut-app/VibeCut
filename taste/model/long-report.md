# The taste model: long vlogs

Learnt 2026-10-24 from 50 long vlogs by 20 creators (seed 0): 886 pairs, each a real edit against a copy the computer damaged in one way. Only numbers and labels went in; none of anyone's video, frames or words.

## Can it tell a real edit from a damaged one?

- On a creator it never saw (leave one creator out): **93%** of pairs.
- On a damage it was never shown (that damage and that creator both left out): **34%** on average.
- 50% is a coin toss; a tie counts half.

| Damage | What the computer did | Creator never seen | Damage never shown |
| --- | --- | --- | --- |
| shuffle_all | every shot in a random order | 100% | 100% |
| swap_neighbours | a few shots swapped with the next one | 84% | 78% |
| even_rhythm | every shot the same length | 98% | 26% |
| permute_durations | the shots in order, their lengths handed out at random | 88% | 64% |
| add_flashes | white flashes on many joins | 100% | 16% |
| add_dissolves | dissolves on many joins | 100% | 0% |
| strip_effects | the creator's effects between shots turned into straight cuts | 27% | 0% |
| quantise_to_beat | every cut moved onto the beat (or a half-second grid) | 98% | 42% |
| cold_open | the held first shot cut to a typical length | 43% | 24% |
| long_open | the first shot held three times as long | 90% | 18% |
| fade_in_out | a fade from black at the start and to black at the end | 100% | 0% |
| no_fades | the creator's fades from or to black taken off | 0% | 0% |
| words_top | the words moved to the top of the frame | 100% | 98% |
| words_off_top | the creator's top-of-frame words moved to the bottom | 100% | 20% |
| words_caps | the words in capitals | 100% | 2% |
| words_lower | the creator's capitals in lower case | 100% | 88% |
| words_everywhere | words over every shot | 98% | 62% |
| words_none | the words taken out | 100% | 64% |
| long_talk | the cutaways between talking shots taken out | 82% | 7% |
| repeat_shot | a shot shown again later on | 98% | 0% |
| music_off | the music taken away | 96% | 45% |
| add_music | music under all of it | 97% | 0% |

A damage the second column can't see is one only that damage teaches; a high first column with a low second one means the model learnt that damage, not editing.

## What it weighs

The strongest signals; a + means the real edits have more of it than the damaged ones.

- -2.62  how much neighbouring shots differ in length, against chance (1: as if in any order)
- -2.53  words at the top more or less often than in the good edits
- +2.28  how much each shot follows on from the one before -- what it shows, how it looks, how it moves -- against two of its shots taken at random (0: as if in any order)
- -2.20  music under less or more of it than in the good edits
- +2.03  share of the time with music under it
- +1.67  share of the words' time at the top of the frame
- -1.61  more or fewer capitals than in the good edits
- -1.46  the longest talk with no cutaway, as a share of the video
- -1.45  share of shots that are a shot shown earlier
- -1.36  shot lengths more even or more uneven than the good edits'
- -1.34  words on fewer or more shots than in the good edits
- -1.23  fewer or more dissolves than in the good edits

## Story jobs (the role model)

Trained on 3601 shots whose job the AI editor named; names a creator's shots right 48% of the time when it never saw that creator, against 28% for always guessing the commonest job. Jobs seen: detail 516, hook 432, other 11, payoff 213, reaction 94, setup 388, step 1013, talk 706, title 40, transit 188.

## Grammar

Shot lengths and joins learnt from 50 videos; what each shot is, by the readings there were: faces, motion, sound (50), faces, motion (50), motion, sound (50), motion (50); story jobs from 50.

## Read with care

- The real side is what these creators did, not proof of what is good; the damaged side is the computer's idea of a mistake. The model learns what separates the two.
- The sample is the creators, not the videos: 20 here. Each creator counts the same however many videos they gave.
- A reading that wasn't taken (no faces off the Mac, no words when Vision didn't run) counts as neither good nor bad.
- Every threshold that turns readings into tokens (quick, held, talking, moving) is a prior.
