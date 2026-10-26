FROM postgres:18

# btree_gist ships with core Postgres; this enables it on first init.
COPY init-extensions.sh /docker-entrypoint-initdb.d/
