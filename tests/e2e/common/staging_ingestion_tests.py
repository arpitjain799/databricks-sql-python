import os
import tempfile

import pytest
import databricks.sql as sql
from databricks.sql import Error

class PySQLStagingIngestionTestSuiteMixin:
    """Simple namespace for ingestion tests. These should be run against DBR >12.x

    In addition to connection credentials (host, path, token) this suite requires an env var
    named staging_ingestion_user"""

    staging_ingestion_user = os.getenv("staging_ingestion_user")

    if staging_ingestion_user is None:
        raise ValueError(
            "To run these tests you must designate a `staging_ingestion_user` environment variable. This will the user associated with the personal access token."
        )

    def test_staging_ingestion_life_cycle(self):
        """PUT a file into the staging location
        GET the file from the staging location
        REMOVE the file from the staging location
        Try to GET the file again expecting to raise an exception
        """

        # PUT should succeed

        fh, temp_path = tempfile.mkstemp()

        original_text = "hello world!".encode("utf-8")

        with open(fh, "wb") as fp:
            fp.write(original_text)

        with self.connection(extra_params={"staging_allowed_local_path": temp_path}) as conn:

            cursor = conn.cursor()
            query = f"PUT '{temp_path}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
            cursor.execute(query)

        # GET should succeed

        new_fh, new_temp_path = tempfile.mkstemp()

        with self.connection(extra_params={"staging_allowed_local_path": new_temp_path}) as conn:
            cursor = conn.cursor()
            query = f"GET 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' TO '{new_temp_path}'"
            cursor.execute(query)

        with open(new_fh, "rb") as fp:
            fetched_text = fp.read()

        assert fetched_text == original_text

        # REMOVE should succeed

        remove_query = (
            f"REMOVE 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv'"
        )

        with self.connection(extra_params={"staging_allowed_local_path": "/"}) as conn:
            cursor = conn.cursor()
            cursor.execute(remove_query)

        # GET after REMOVE should fail

            with pytest.raises(Error):
                cursor = conn.cursor()
                query = f"GET 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' TO '{new_temp_path}'"
                cursor.execute(query)

        os.remove(temp_path)
        os.remove(new_temp_path)


    def test_staging_ingestion_put_fails_without_staging_allowed_local_path(self):
        """PUT operations are not supported unless the connection was built with
        a parameter called staging_allowed_local_path
        """

        fh, temp_path = tempfile.mkstemp()

        original_text = "hello world!".encode("utf-8")

        with open(fh, "wb") as fp:
            fp.write(original_text)

        with pytest.raises(Error):
            with self.connection() as conn:
                cursor = conn.cursor()
                query = f"PUT '{temp_path}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
                cursor.execute(query)

    def test_staging_ingestion_put_fails_if_localFile_not_in_staging_allowed_local_path(self):


        fh, temp_path = tempfile.mkstemp()

        original_text = "hello world!".encode("utf-8")

        with open(fh, "wb") as fp:
            fp.write(original_text)

        base_path, filename = os.path.split(temp_path)

        # Add junk to base_path
        base_path = os.path.join(base_path, "temp")

        with pytest.raises(Error):
            with self.connection(extra_params={"staging_allowed_local_path": base_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{temp_path}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
                cursor.execute(query)

    def test_staging_ingestion_put_fails_if_file_exists_and_overwrite_not_set(self):
        """PUT a file into the staging location twice. First command should succeed. Second should fail.
        """

        fh, temp_path = tempfile.mkstemp()

        original_text = "hello world!".encode("utf-8")

        with open(fh, "wb") as fp:
            fp.write(original_text)

        def perform_put():
            with self.connection(extra_params={"staging_allowed_local_path": temp_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{temp_path}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/12/15/file1.csv'"
                cursor.execute(query)

        def perform_remove():
            remove_query = (
                f"REMOVE 'stage://tmp/{self.staging_ingestion_user}/tmp/12/15/file1.csv'"
            )

            with self.connection(extra_params={"staging_allowed_local_path": "/"}) as conn:
                cursor = conn.cursor()
                cursor.execute(remove_query)


        # Make sure file does not exist
        perform_remove()

        # Put the file
        perform_put()

        # Try to put it again
        with pytest.raises(sql.exc.ServerOperationError, match="FILE_IN_STAGING_PATH_ALREADY_EXISTS"):
            perform_put()

        # Clean up after ourselves
        perform_remove()
        
    def test_staging_ingestion_fails_to_modify_another_staging_user(self):
        """The server should only allow modification of the staging_ingestion_user's files
        """

        some_other_user = "mary.poppins@databricks.com"

        fh, temp_path = tempfile.mkstemp()

        original_text = "hello world!".encode("utf-8")

        with open(fh, "wb") as fp:
            fp.write(original_text)

        def perform_put():
            with self.connection(extra_params={"staging_allowed_local_path": temp_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{temp_path}' INTO 'stage://tmp/{some_other_user}/tmp/12/15/file1.csv' OVERWRITE"
                cursor.execute(query)

        def perform_remove():
            remove_query = (
                f"REMOVE 'stage://tmp/{some_other_user}/tmp/12/15/file1.csv'"
            )

            with self.connection(extra_params={"staging_allowed_local_path": "/"}) as conn:
                cursor = conn.cursor()
                cursor.execute(remove_query)

        def perform_get():
            with self.connection(extra_params={"staging_allowed_local_path": temp_path}) as conn:
                cursor = conn.cursor()
                query = f"GET 'stage://tmp/{some_other_user}/tmp/11/15/file1.csv' TO '{temp_path}'"
                cursor.execute(query)

        # PUT should fail with permissions error
        with pytest.raises(sql.exc.ServerOperationError, match="PERMISSION_DENIED"):
            perform_put()

        # REMOVE should fail with permissions error
        with pytest.raises(sql.exc.ServerOperationError, match="PERMISSION_DENIED"):
            perform_remove()

        # GET should fail with permissions error
        with pytest.raises(sql.exc.ServerOperationError, match="PERMISSION_DENIED"):
            perform_get()

    def test_staging_ingestion_put_fails_if_absolute_localFile_not_in_staging_allowed_local_path(self):
        """
        This test confirms that staging_allowed_local_path and target_file are resolved into absolute paths.
        """

        # If these two paths are not resolved absolutely, they appear to share a common path of /var/www/html
        # after resolution their common path is only /var/www which should raise an exception
        # Because the common path must always be equal to staging_allowed_local_path
        staging_allowed_local_path = "/var/www/html"
        target_file = "/var/www/html/../html1/not_allowed.html"

        with pytest.raises(Error):
            with self.connection(extra_params={"staging_allowed_local_path": staging_allowed_local_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{target_file}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
                cursor.execute(query)

    def test_staging_ingestion_empty_local_path_fails_to_parse_at_server(self):
        staging_allowed_local_path = "/var/www/html"
        target_file = ""

        with pytest.raises(Error, match="EMPTY_LOCAL_FILE_IN_STAGING_ACCESS_QUERY"):
            with self.connection(extra_params={"staging_allowed_local_path": staging_allowed_local_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{target_file}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
                cursor.execute(query)

    def test_staging_ingestion_invalid_staging_path_fails_at_server(self):
        staging_allowed_local_path = "/var/www/html"
        target_file = "index.html"

        with pytest.raises(Error, match="INVALID_STAGING_PATH_IN_STAGING_ACCESS_QUERY"):
            with self.connection(extra_params={"staging_allowed_local_path": staging_allowed_local_path}) as conn:
                cursor = conn.cursor()
                query = f"PUT '{target_file}' INTO 'stageRANDOMSTRINGOFCHARACTERS://tmp/{self.staging_ingestion_user}/tmp/11/15/file1.csv' OVERWRITE"
                cursor.execute(query)

    def test_staging_ingestion_supports_multiple_staging_allowed_local_path_values(self):
        """staging_allowed_local_path may be either a path-like object or a list of path-like objects.

        This test confirms that two configured base paths:
        1 - doesn't raise an exception
        2 - allows uploads from both paths
        3 - doesn't allow uploads from a third path
        """

        def generate_file_and_path_and_queries():
            """
                1. Makes a temp file with some contents.
                2. Write a query to PUT it into a staging location
                3. Write a query to REMOVE it from that location (for cleanup)
            """
            fh, temp_path = tempfile.mkstemp()
            with open(fh, "wb") as fp:
                original_text = "hello world!".encode("utf-8")
                fp.write(original_text)
            put_query = f"PUT '{temp_path}' INTO 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/{id(temp_path)}.csv' OVERWRITE"
            remove_query = f"REMOVE 'stage://tmp/{self.staging_ingestion_user}/tmp/11/15/{id(temp_path)}.csv'"
            return fh, temp_path, put_query, remove_query

        fh1, temp_path1, put_query1, remove_query1 = generate_file_and_path_and_queries()
        fh2, temp_path2, put_query2, remove_query2 = generate_file_and_path_and_queries()
        fh3, temp_path3, put_query3, remove_query3 = generate_file_and_path_and_queries()

        with self.connection(extra_params={"staging_allowed_local_path": [temp_path1, temp_path2]}) as conn:
            cursor = conn.cursor()

            cursor.execute(put_query1)
            cursor.execute(put_query2)
            
            with pytest.raises(Error, match="Local file operations are restricted to paths within the configured staging_allowed_local_path"):
                cursor.execute(put_query3)

            # Then clean up the files we made
            cursor.execute(remove_query1)
            cursor.execute(remove_query2)