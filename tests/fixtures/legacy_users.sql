CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT,
                card TEXT,
                sex TEXT DEFAULT '0',
                age INTEGER DEFAULT 0,
                city TEXT DEFAULT '通辽',
                permission INTEGER DEFAULT 0,
                signed_days TEXT,
                registration_date TEXT,
                ai_token_record INTEGER DEFAULT 0,
                user_portrait TEXT DEFAULT '',
                portrait_update_time TEXT DEFAULT ''
                ,intimacy INTEGER DEFAULT 0
            )
