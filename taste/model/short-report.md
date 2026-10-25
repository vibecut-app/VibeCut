# The taste model: shorts

Learnt 2026-10-24 from 37 shorts by 17 creators (seed 0): 679 pairs, each a real edit against a copy the computer damaged in one way. Only numbers and labels went in; none of anyone's video, frames or words.

## Can it tell a real edit from a damaged one?

- On a creator it never saw (leave one creator out): **87%** of pairs.
- On a damage it was never shown (that damage and that creator both left out): **26%** on average.
- 50% is a coin toss; a tie counts half.

| Damage | What the computer did | Creator never seen | Damage never shown |
| --- | --- | --- | --- |
| shuffle_all | every shot in a random order | 100% | 100% |
| swap_neighbours | a few shots swapped with the next one | 68% | 68% |
| even_rhythm | every shot the same length | 95% | 0% |
| permute_durations | the shots in order, their lengths handed out at random | 81% | 65% |
| add_flashes | white flashes on many joins | 97% | 95% |
| add_dissolves | dissolves on many joins | 97% | 14% |
| strip_effects | the creator's effects between shots turned into straight cuts | 0% | 0% |
| quantise_to_beat | every cut moved onto the beat (or a half-second grid) | 89% | 3% |
| cold_open | the held first shot cut to a typical length | 5% | 0% |
| long_open | the first shot held three times as long | 84% | 5% |
| fade_in_out | a fade from black at the start and to black at the end | 97% | 0% |
| no_fades | the creator's fades from or to black taken off | 80% | 0% |
| words_top | the words moved to the top of the frame | 100% | 14% |
| words_off_top | the creator's top-of-frame words moved to the bottom | 93% | 43% |
| words_caps | the words in capitals | 100% | 0% |
| words_lower | the creator's capitals in lower case | 77% | 8% |
| words_everywhere | words over every shot | 84% | 16% |
| words_none | the words taken out | 89% | 0% |
| long_talk | the cutaways between talking shots taken out | 80% | 80% |
| repeat_shot | a shot shown again later on | 100% | 60% |
| stretch_ending | the last shot held three times as long | 97% | 17% |
| cold_ending | the held last shot cut to a typical length | 24% | 18% |
| music_off | the music taken away | 88% | 27% |
| add_music | music under all of it | 100% | 0% |

A damage the second column can't see is one only that damage teaches; a high first column with a low second one means the model learnt that damage, not editing.

## What it weighs

The strongest signals; a + means the real edits have more of it than the damaged ones.

- -2.20  music under less or more of it than in the good edits
- -2.15  words at the top more or less often than in the good edits
- -2.09  words on fewer or more shots than in the good edits
- +2.06  share of the time with music under it
- -1.88  more or fewer capitals than in the good edits
- -1.71  share of shots that are a shot shown earlier
- +1.68  share of the words' time at the top of the frame
- -1.65  share of the time with words on screen
- +1.45  how much of the words is in capitals
- +1.38  how much the order of quick and held shots follows the good edits, beyond the lengths
- -1.36  less or more talk over music than in the good edits
- -1.32  the longest shot inside standing out less or more than in the good edits

## Story jobs (the role model)

Not trained: on a creator it never saw it names 52% of jobs right, against 47% for always guessing the commonest.

## Grammar

Shot lengths and joins learnt from 37 videos; what each shot is, by the readings there were: faces, motion, sound (37), faces, motion (37), motion, sound (37), motion (37); story jobs from 37.

## Read with care

- The real side is what these creators did, not proof of what is good; the damaged side is the computer's idea of a mistake. The model learns what separates the two.
- The sample is the creators, not the videos: 17 here. Each creator counts the same however many videos they gave.
- A reading that wasn't taken (no faces off the Mac, no words when Vision didn't run) counts as neither good nor bad.
- Every threshold that turns readings into tokens (quick, held, talking, moving) is a prior.
