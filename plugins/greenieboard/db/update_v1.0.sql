ALTER TABLE greenieboard ADD COLUMN mission_id INTEGER NOT NULL DEFAULT -1;
ALTER TABLE greenieboard ADD COLUMN trapsheet TEXT;
DELETE FROM greenieboard;
INSERT INTO greenieboard (mission_id, player_ucid, unit_type, grade, comment, place, night, points, time) SELECT mission_id, init_id, init_type, grade, comment, place, FALSE, CASE WHEN grade = '_OK_' THEN 5 WHEN grade = 'OK' THEN 4 WHEN grade = '(OK)' THEN 3 WHEN grade = 'B' THEN 2.5 WHEN grade IN('---', 'OWO', 'WOP') THEN 2 WHEN grade IN ('WO', 'LIG') THEN 1 WHEN grade = 'C' THEN 0 END AS points, time FROM (SELECT mission_id, init_id, init_type, SUBSTRING(comment, 'LSO: GRADE:([_\(\)-BCKOW]{1,4})') AS grade, comment, place, time FROM missionstats WHERE event LIKE '%QUALITY%') AS landings;
