CREATE TABLE revisions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	level VARCHAR(8) NOT NULL, 
	table_name VARCHAR(255), 
	column_name VARCHAR(255), 
	before_text TEXT, 
	after_text TEXT, 
	actor VARCHAR(128), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE TABLE sources (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(200) NOT NULL, 
	dialect VARCHAR(32) NOT NULL, 
	host VARCHAR(255) NOT NULL, 
	port INTEGER NOT NULL, 
	database_name VARCHAR(255) NOT NULL, 
	db_schema VARCHAR(255) NOT NULL, 
	username VARCHAR(255), 
	secret_ref TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE TABLE runs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_key VARCHAR(64) NOT NULL, 
	source_id INTEGER, 
	name VARCHAR(255) NOT NULL, 
	schema_name VARCHAR(255), 
	domain VARCHAR(255), 
	db_description TEXT, 
	ai_db_description TEXT, 
	model VARCHAR(128), 
	status VARCHAR(32) NOT NULL, 
	with_truth BOOL NOT NULL, 
	graph_id VARCHAR(64), 
	table_count INTEGER NOT NULL, 
	column_count INTEGER NOT NULL, 
	score JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

CREATE TABLE cat_tables (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	row_count BIGINT NOT NULL, 
	pk_columns VARCHAR(512), 
	pk_source VARCHAR(32), 
	original_comment TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_run_table UNIQUE (run_id, name), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
);

CREATE TABLE concepts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	name_ko VARCHAR(255), 
	description TEXT, 
	synonyms TEXT, 
	is_a VARCHAR(255), 
	confidence FLOAT, 
	mapped_tables JSON, 
	key_columns JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
);

CREATE TABLE descriptions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	level VARCHAR(8) NOT NULL, 
	table_name VARCHAR(255), 
	column_name VARCHAR(255), 
	ai_text TEXT, 
	current_text TEXT, 
	confidence FLOAT, 
	edited BOOL NOT NULL, 
	reviewed_by VARCHAR(128), 
	reviewed_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_desc UNIQUE (run_id, level, table_name, column_name), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
);

CREATE TABLE cat_columns (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	table_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	data_type VARCHAR(128) NOT NULL, 
	nullable BOOL NOT NULL, 
	is_pk BOOL NOT NULL, 
	fk_ref VARCHAR(512), 
	fk_source VARCHAR(32), 
	original_comment TEXT, 
	data_unverified BOOL NOT NULL, 
	stats JSON, 
	evidence JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_table_col UNIQUE (table_id, name), 
	FOREIGN KEY(table_id) REFERENCES cat_tables (id)
);
