"""The world's dumbest file for testing garbage"""

from youtubesearchpython import PlaylistsSearch, Playlist, ResultMode, Search

s = Search('https://www.youtube.com/watch?v=zmbBhEts7t4').result()

print('?list=PL' in 'https://www.youtube.com/playlist?list=PLy6N_9yB8Qwy6LL0J7zLUyW8XNX-BPeDl')