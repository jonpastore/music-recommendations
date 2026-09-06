import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.plex_matching import match_tracks
from app.plex import Plex
from app.providers import ProviderError


def song(key, title='Song', artist='Artist', album='Album', duration=200000):
    return {'rating_key': str(key), 'title': title, 'artist': artist, 'album': album, 'duration_ms': duration}


def source(title='Song', artist='Artist', album='Album', duration=200000):
    return {'title': title, 'artist': artist, 'album': album, 'duration_ms': duration}


class MatchingTests(unittest.TestCase):
    def test_exact_match_missing_and_ambiguous_are_distinct(self):
        rows = match_tracks([source(), source('Unknown'), source('Other')],
                            [song(1), song(2,'Other'), song(3,'Other')], {})
        self.assertEqual(['matched','missing','ambiguous'], [r['status'] for r in rows])
        self.assertEqual('1', rows[0]['match']['rating_key'])
        self.assertEqual(2, len(rows[2]['candidates']))

    def test_versions_and_duration_mismatches_need_review(self):
        for candidate in [song(1, album='Live album'), song(1, duration=350000), song(1,title='Song (Live)')]:
            row = match_tracks([source()], [candidate], {})[0]
            self.assertNotEqual('matched', row['status'])
            self.assertIsNone(row['match'])

    def test_normalizes_punctuation_but_preserves_repeated_source_rows(self):
        rows = match_tracks([source('Café!'), source('Café!')], [song(1,'Cafe')], {})
        self.assertEqual([0,1], [r['index'] for r in rows])
        self.assertEqual(['1','1'], [r['match']['rating_key'] for r in rows])

    def test_album_unknown_does_not_hide_duplicate_candidates(self):
        row = match_tracks([source(album=None)], [song(1),song(2,album='Compilation')], {})[0]
        self.assertEqual('ambiguous', row['status'])

    def test_all_versions_remain_available_for_manual_choice(self):
        row=match_tracks([source()], [song(i) for i in range(12)], {})[0]
        self.assertEqual(12,len(row['candidates']))

    def test_large_candidate_cross_product_fails_before_response_growth(self):
        with self.assertRaisesRegex(ProviderError,'too many Plex versions'):
            match_tracks([source()]*5000,[song(i) for i in range(5)],{})


class PlexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.config = {'PLEX_URL':'http://plex:32400', 'PLEX_TOKEN':'secret', 'PLEX_MUSIC_LIBRARY':'Music'}
        factory = patch('app.plex.PlexServer')
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.server = self.factory.return_value
        self.server.machineIdentifier='server123'
        self.server.friendlyName='Home Plex'
        self.section=self.server.library.section.return_value
        self.section.type='artist'; self.section.key='2'; self.section.title='Music'
        self.items = [SimpleNamespace(ratingKey=1,title='Song',grandparentTitle='Artist',originalTitle=None,parentTitle='Album',duration=200000)]
        self.section.searchTracks.return_value=self.items
        self.server.playlists.return_value=[]
        self.client=Plex(self.config,self.directory)
        self.payload={'source':'spotify','playlist_name':'Mix','playlist_url':'https://open.spotify.com/playlist/abc','tracks':[source(),source('Missing'),source()]}

    def test_missing_configuration_never_connects(self):
        with self.assertRaisesRegex(ProviderError,'PLEX_URL'):
            Plex({}, self.directory).match(self.payload)
        self.factory.assert_not_called()

    def test_matches_can_be_restored_without_losing_full_order(self):
        scan=self.client.match(self.payload)
        self.assertEqual({'total':3,'matched':2,'missing':1,'ambiguous':0,'skipped':0},scan['counts'])
        restored=Plex(self.config,self.directory).get_scan(scan['scan_id'])
        self.assertEqual(self.payload['tracks'], [r['track'] for r in restored['rows']])
        self.assertEqual(1,len(self.client.drafts()))
        self.assertEqual(0o600,(self.directory/'plex-state.json').stat().st_mode & 0o777)

    def test_rejects_arbitrary_rating_key_and_configuration_changes(self):
        scan=self.client.match(self.payload)
        with self.assertRaises(ProviderError): self.client.choose(scan['scan_id'],0,'999')
        with self.assertRaises(ProviderError): Plex({**self.config,'PLEX_TOKEN':'different'},self.directory).get_scan(scan['scan_id'])
        self.server.createPlaylist.assert_not_called()

    def test_selected_ambiguous_match_is_remembered_on_recheck(self):
        self.items.append(SimpleNamespace(**{**vars(self.items[0]),'ratingKey':2}))
        scan=self.client.match(self.payload)
        self.assertEqual('ambiguous',scan['rows'][0]['status'])
        changed=self.client.choose(scan['scan_id'],0,'2')
        self.assertEqual('2',changed['rows'][0]['match']['rating_key'])
        rechecked=self.client.match(self.payload)
        self.assertEqual('2',rechecked['rows'][0]['match']['rating_key'])

    def test_creates_only_matched_tracks_in_order_with_duplicates(self):
        scan=self.client.match(self.payload)
        playlist=Mock(ratingKey=12,title='Mix',playlistType='audio',smart=False)
        playlist.items.return_value=[self.items[0],self.items[0]]
        self.server.createPlaylist.return_value=playlist
        result=self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.assertEqual([1,1],[t.ratingKey for t in self.server.createPlaylist.call_args.kwargs['items']])
        self.assertEqual(2,result['tracks']); self.assertEqual(1,result['omitted'])
        self.assertNotIn('secret',result['web_url'])
        self.server.fetchItem.return_value=playlist
        repeat=self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.assertEqual('unchanged',repeat['action'])
        self.assertEqual(1,self.server.createPlaylist.call_count)

    def test_never_overwrites_an_unmanaged_same_name_playlist(self):
        scan=self.client.match(self.payload)
        self.server.playlists.return_value=[Mock(title='Mix',ratingKey=99)]
        with self.assertRaisesRegex(ProviderError,'already exists'):
            self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.server.createPlaylist.assert_not_called()

    def test_zero_matches_do_not_create_empty_playlist(self):
        scan=self.client.match({**self.payload,'tracks':[source('Absent')]})
        with self.assertRaises(ProviderError): self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.server.createPlaylist.assert_not_called()

    def test_deleted_matched_track_requires_recheck(self):
        scan=self.client.match(self.payload)
        self.section.searchTracks.return_value=[]
        with self.assertRaisesRegex(ProviderError,'[Rr]echeck'):
            self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.server.createPlaylist.assert_not_called()

    def test_update_appends_before_removing_occurrences_and_resumes_after_failure(self):
        scan=self.client.match(self.payload)
        first=SimpleNamespace(**vars(self.items[0]),playlistItemID=10)
        second=SimpleNamespace(**vars(self.items[0]),playlistItemID=11)
        playlist=Mock(ratingKey=12,title='Mix',playlistType='audio',smart=False)
        contents=[first,second]
        playlist.items.side_effect=lambda: list(contents)
        self.server.createPlaylist.return_value=playlist
        self.client.save_playlist(scan['scan_id'],'create','Mix')
        # User removes one repeated song from the new source list.
        scan=self.client.match({**self.payload,'tracks':[source()]})
        self.server.fetchItem.return_value=playlist
        def append(items):
            contents.append(SimpleNamespace(**vars(items[0]),playlistItemID=20))
        playlist.addItems.side_effect=append
        events=[]
        def remove(path, method):
            self.assertEqual([1,1,1],[item.ratingKey for item in contents] if not events else [1,1])
            identifier=int(path.rsplit('/',1)[1]); events.append(identifier)
            contents[:]=[item for item in contents if item.playlistItemID!=identifier]
            if identifier==10:
                import requests
                raise requests.Timeout('delete accepted but response lost')
        self.server.query.side_effect=remove
        import requests
        with self.assertRaises(requests.Timeout): self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.server.query.side_effect=lambda path,method: contents.__setitem__(slice(None),[item for item in contents if item.playlistItemID!=int(path.rsplit('/',1)[1])])
        result=self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.assertEqual('updated',result['action'])
        self.assertEqual([20],[item.playlistItemID for item in contents])
        playlist.addItems.assert_called_once()

    def test_unconfirmed_append_does_not_delete_original_items(self):
        scan=self.client.match(self.payload)
        playlist=Mock(ratingKey=12,title='Mix',playlistType='audio',smart=False)
        playlist.items.return_value=[self.items[0],self.items[0]]
        self.server.createPlaylist.return_value=playlist
        self.client.save_playlist(scan['scan_id'],'create','Mix')
        scan=self.client.match({**self.payload,'tracks':[source()]})
        self.server.fetchItem.return_value=playlist
        playlist.items.return_value=[SimpleNamespace(**vars(self.items[0]),playlistItemID=10),SimpleNamespace(**vars(self.items[0]),playlistItemID=11)]
        with self.assertRaisesRegex(ProviderError,'original playlist'):
            self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.server.query.assert_not_called()

    def test_partial_append_resumes_remaining_tracks_in_small_batches(self):
        import requests
        from app.plex import BATCH_SIZE
        scan=self.client.match(self.payload)
        playlist=Mock(ratingKey=12,title='Mix',playlistType='audio',smart=False)
        contents=[SimpleNamespace(**vars(self.items[0]),playlistItemID=i) for i in (10,11)]
        playlist.items.side_effect=lambda:list(contents)
        self.server.createPlaylist.return_value=playlist
        self.client.save_playlist(scan['scan_id'],'create','Mix')
        scan=self.client.match({**self.payload,'tracks':[source()]*(BATCH_SIZE+3)})
        self.server.fetchItem.return_value=playlist
        failed=False
        def append(items):
            nonlocal failed
            self.assertLessEqual(len(items),BATCH_SIZE)
            count=2 if not failed else len(items)
            for item in items[:count]:
                contents.append(SimpleNamespace(**vars(item),playlistItemID=100+len(contents)))
            if not failed:
                failed=True
                raise requests.Timeout('partial append')
        playlist.addItems.side_effect=append
        self.server.query.side_effect=lambda path,method:contents.__setitem__(slice(None),[i for i in contents if i.playlistItemID!=int(path.rsplit('/',1)[1])])
        with self.assertRaises(requests.Timeout):self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.server.query.assert_not_called()
        with self.assertRaisesRegex(ProviderError,'unfinished Plex save'):
            self.client.choose(scan['scan_id'],0,None)
        self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.assertEqual(BATCH_SIZE+3,len(contents))
        self.assertEqual(BATCH_SIZE+3,sum(len(c.args[0]) for c in playlist.addItems.call_args_list[1:])+2)

    def test_uncertain_create_is_recovered_without_duplicate_or_large_requests(self):
        import requests
        from app.plex import BATCH_SIZE
        scan=self.client.match({**self.payload,'tracks':[source()]*(BATCH_SIZE+3)})
        playlist=Mock(ratingKey=12,playlistType='audio',smart=False)
        contents=[]
        playlist.items.side_effect=lambda:list(contents)
        def create(title,items):
            self.assertLessEqual(len(items),BATCH_SIZE)
            playlist.title=title
            contents.extend(SimpleNamespace(**vars(item),playlistItemID=i+1) for i,item in enumerate(items))
            self.server.playlists.return_value=[playlist]
            raise requests.Timeout('created but response lost')
        self.server.createPlaylist.side_effect=create
        self.server.fetchItem.return_value=playlist
        playlist.addItems.side_effect=lambda items:contents.extend(SimpleNamespace(**vars(item),playlistItemID=1000+i) for i,item in enumerate(items))
        playlist.editTitle.side_effect=lambda title:setattr(playlist,'title',title)
        with self.assertRaises(requests.Timeout):self.client.save_playlist(scan['scan_id'],'create','Mix')
        result=self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.assertEqual('created',result['action'])
        self.assertEqual('Mix',playlist.title)
        self.assertEqual(BATCH_SIZE+3,len(contents))
        self.server.createPlaylist.assert_called_once()

    def test_deleted_managed_playlist_can_be_explicitly_recreated(self):
        from plexapi.exceptions import NotFound
        scan=self.client.match(self.payload)
        playlist=Mock(ratingKey=12,title='Mix',playlistType='audio',smart=False)
        playlist.items.return_value=[self.items[0],self.items[0]]
        self.server.createPlaylist.return_value=playlist
        self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.server.fetchItem.side_effect=NotFound('deleted')
        with self.assertRaisesRegex(ProviderError,'deleted'):
            self.client.save_playlist(scan['scan_id'],'update','Mix')
        self.assertIsNone(self.client.get_scan(scan['scan_id'])['managed_playlist'])
        self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.assertEqual(2,self.server.createPlaylist.call_count)

    def test_same_address_replaced_server_invalidates_restores_and_choices(self):
        scan=self.client.match(self.payload)
        self.server.machineIdentifier='replacement'
        with self.assertRaisesRegex(ProviderError,'changed'):self.client.get_scan(scan['scan_id'])
        with self.assertRaisesRegex(ProviderError,'changed'):self.client.choose(scan['scan_id'],0,'1')
        self.assertEqual([],self.client.drafts())

    def test_reused_rating_key_requires_recheck_before_saving(self):
        scan=self.client.match(self.payload)
        self.items[0].title='Different Song'
        with self.assertRaisesRegex(ProviderError,'[Rr]echeck'):
            self.client.save_playlist(scan['scan_id'],'create','Mix')
        self.server.createPlaylist.assert_not_called()

    def test_various_artist_album_uses_track_artist(self):
        self.items[0].grandparentTitle='Various Artists'
        self.items[0].originalTitle='Artist'
        self.assertEqual('matched',self.client.match(self.payload)['rows'][0]['status'])

    def test_wrong_library_type_is_actionable(self):
        self.section.type='movie'
        with self.assertRaisesRegex(ProviderError,'music library'):
            self.client.match(self.payload)
