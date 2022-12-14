from table_schema import SchemaLoader
import helper_loading as h
from psycopg2 import sql
import pandas as pd
import pandas.io.sql as io_sql
from datetime import datetime
from time import time
import numpy
import json
import os
import warnings
warnings.filterwarnings('ignore')

class EuroDatabaseLoader(SchemaLoader):
    '''
    The present class inherits the 'SchemaLoader' class of 'table_schema' module.
    It uses the inherited methods and variables, as well as, the helper functions of 'helper_loading' module. 
    It also introduces two instance variables and two types of methods.
    The 1st type ('implement_table_loading') implements the loading process by making use of the 2nd type of methods.
    The 2nd type ('extract_and_load_{table_name}') handles the extraction, transformation and loading of the data.
    '''
    def __init__(self, connection, postgres_tables, season_codes):
        
        super().__init__(connection)

        # the next two instance variables correspond to the two command line arguments
        self.postgres_tables = postgres_tables
        self.season_codes = season_codes

    def implement_table_loading(self):
        '''
        This is the main instance method of the class. It makes use of the remaining instance methods.
        '''  
        for table in self.postgres_tables:
            
            print("\n-----------------------------------------------------------------------------------------------------")
            
            self.cursor.execute(f"CREATE TABLE IF NOT EXISTS {table} ()")
            self.add_columns(table)
            table_column_names = self.table_column_names[table]
            index = self.create_unique_index(table)
            
            sql_insert = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING")\
                            .format(sql.SQL(table),
                                    sql.SQL(', ').join(map(sql.Identifier, table_column_names)), 
                                    sql.SQL(', ').join(sql.Placeholder() * len(table_column_names)),
                                    sql.SQL(index))
            
            start_table = time()

            for season_code in self.season_codes:
                
                start_season = time()
                
                print(f"\nLoading {table.upper()}: SeasonCode {season_code}")
                json_success_filenames = os.listdir(fr"../euroleague_json_data/{season_code}/success")
                json_success_filenames_header = [filename for filename in json_success_filenames \
                                                 if "Header" in filename and filename \
                                                 != "E2018_RegularSeason_03_021_20181019_Header.json"]
                getattr(self, f"extract_and_load_{table}")(season_code, json_success_filenames, json_success_filenames_header, sql_insert)
                print("TimeCounterSeason", round(time() - start_season, 1), "sec  --- ", "TimeCounterTable:", round(time() - start_table, 1), "sec")
                
            if table == 'box_score':
                
                # load players
                
                self.cursor.execute(f"DROP TABLE IF EXISTS players");
                self.cursor.execute(f"CREATE TABLE players ()")
                self.add_columns('players')
                table_column_names_players = self.table_column_names['players']
                index_players = self.create_unique_index('players')

                sql_insert_players = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING")\
                                        .format(sql.SQL('players'),
                                                sql.SQL(', ').join(map(sql.Identifier, table_column_names_players)), 
                                                sql.SQL(', ').join(sql.Placeholder() * len(table_column_names_players)),
                                                sql.SQL('season_player_id'))
                
                start_players = time()
                print("\n-----------------------------------------------------------------------------------------------------")
                print(f"\nLoading PLAYERS: all available seasons at once")
                self.extract_and_load_players(sql_insert_players)
                print("TimeCounterTable", round(time() - start_players, 1), "sec")
                
                # load teams
                
                self.cursor.execute(f"DROP TABLE IF EXISTS teams");
                self.cursor.execute(f"CREATE TABLE teams ()")
                self.add_columns('teams')
                table_column_names_teams = self.table_column_names['teams']
                index_teams = self.create_unique_index('teams')

                sql_insert_teams = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING")\
                                        .format(sql.SQL('teams'),
                                                sql.SQL(', ').join(map(sql.Identifier, table_column_names_teams)), 
                                                sql.SQL(', ').join(sql.Placeholder() * len(table_column_names_teams)),
                                                sql.SQL('season_team_id'))
                
                start_teams = time()
                print("\n-----------------------------------------------------------------------------------------------------")
                print(f"\nLoading TEAMS: all available seasons at once")
                self.extract_and_load_teams(sql_insert_teams)
                print("TimeCounterTable", round(time() - start_teams, 1), "sec")
                
    def extract_and_load_header(self, season_code, json_success_filenames, json_success_filenames_header, sql_insert):

        ######### EXTRACT & TRANSFORM #########
        
        # get the json files of box_score
        json_success_filenames_box = [filename for filename in json_success_filenames \
                                      if "Box" in filename and filename \
                                      != "E2018_RegularSeason_03_021_20181019_Boxscore.json"]

        # extract data from the json files of header
        dfs_header = []
        for json_filename in json_success_filenames_header:
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            df_json = pd.read_json(fr"../euroleague_json_data/{season_code}/success/{json_filename}", orient="index").transpose()
            Date, Hour = df_json.iloc[0][["Date", "Hour"]]
            date_converted = datetime.strptime(Date, "%d/%m/%Y").date()
            time_converted = datetime.strptime(Hour.strip(), "%H:%M").time()
            df = pd.DataFrame()
            for key, value in self.map_table_columns_to_json_header.items():
                df[key] = df_json[value]
            df.insert(0, "time", [time_converted])
            df.insert(0, "date", [date_converted])
            df.insert(0, "game", df[["code_team_a", "code_team_b"]].agg("-".join, axis=1))            
            df.insert(0, "game_id", [game_id])
            dfs_header.append(df)          
        df_header = pd.concat(dfs_header)

        # extract data from the json files of box_score
        dfs_box_score = []
        for json_filename in json_success_filenames_box:
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            json_path = fr"../euroleague_json_data/{season_code}/success/{json_filename}"
            json_file = open(json_path)
            json_data = json.load(json_file)
            json_file.close()
            extra_time_columns = [("score_extra_time_1_a", "score_extra_time_2_a", "score_extra_time_3_a"),
                                  ("score_extra_time_1_b", "score_extra_time_2_b", "score_extra_time_3_b")]
            df = h.get_extra_time_df(extra_time_columns, json_data, self.map_table_columns_to_json_box)
            df.insert(0, "game_id", [game_id])
            dfs_box_score.append(df)            
        df_box_score = pd.concat(dfs_box_score)

        # combine data from header and box_score
        df_merged = pd.merge(df_header, df_box_score, how="outer", on="game_id")
        df_merged["date"] = df_merged["date"].fillna(datetime(1970,1,1).date())
        df_merged["time"] = df_merged["time"].fillna(datetime(1970,1,1).time())
        
        # get the number of rows of the dataframe
        number_of_rows = df_merged.shape[0]
        
        # strip columns that might contain redundant empty spaces
        df_merged = h.strip_header(df_merged)

        # replace numpy null values (if any) with empty strings
        df_merged = df_merged.replace(numpy.nan, "")

        ######### LOAD #########

        # load data on header table (populate per season)
        for i in range(number_of_rows):

            try:
                
                data_insert = [value if df_merged.columns[j] in ["date", "time"] \
                               else str(value) for j, value in enumerate(df_merged.iloc[i])]
                self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                self.connection.commit()

            except Exception as e:

                print(e, "\ngame_id:", df_merged.iloc[i]["game_id"], "\n")
                    
    def extract_and_load_box_score(self, season_code, json_success_filenames, json_success_filenames_header, sql_insert):

        ######### EXTRACT & TRANSFORM #########

        # extract data from the json files of header
        df_game_header = h.get_game_header_df(json_success_filenames_header, season_code)
        
        # get the json files of box_score
        json_success_filenames_box = [filename for filename in json_success_filenames \
                                      if "Box" in filename and filename \
                                      != "E2018_RegularSeason_03_021_20181019_Boxscore.json"]
              
        # extract data from the json files of box_score
        for json_filename in json_success_filenames_box:

            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            
            json_path = fr"../euroleague_json_data/{season_code}/success/{json_filename}"
            json_file = open(json_path)
            json_data = json.load(json_file)
            json_file.close()

            data_a, data_b = json_data["Stats"]
            try:
                stats_a = h.get_team_stats(data_a)
            except Exception as e:
                print(e, game_id)
                exit()
            stats_b = h.get_team_stats(data_b)
            box_score = stats_a + stats_b

            df_box_score = pd.DataFrame(box_score)
            number_of_rows = df_box_score.shape[0]
            
            player_ids = df_box_score["Player_ID"]
            game_player_ids = [f"{game_id}_{player_id}" for player_id in player_ids]
            df_box_score.insert(0, "game_id", [game_id for i in range(number_of_rows)])
            df_box_score.insert(0, "game_player_id", game_player_ids)
            df_box_score["IsPlaying"].mask(~df_box_score["Minutes"].str.contains("DNP"), 1, inplace=True)

            # combine data from header and box_score
            df_merged = pd.merge(df_box_score, df_game_header, how="left", on="game_id")
            
            # strip columns that might contain redundant empty spaces
            df_merged = h.strip_box_score(df_merged)
            
            # re-order columns and replace numpy null values (if any) with empty strings
            columns_reordered = ["game_player_id", "game_id", "game", "round", "phase", "season_code"] \
                                + list(df_merged.columns[2:-4])
            df_merged = df_merged[columns_reordered].replace(numpy.nan, "")
  
            ######### LOAD #########

            # load data on box_score table (populate per file)
            for i in range(number_of_rows):

                try:

                    data_insert = [str(value) for value in df_merged.iloc[i]]
                    self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                    self.connection.commit()

                except Exception as e:

                    print(e, "\ngame_player_id:", df_merged.iloc[i]["game_player_id"], "\n")

    def extract_and_load_players(self, sql_insert):

        ######### EXTRACT #########

        query = f"select * from box_score"
        df_box = io_sql.read_sql_query(query, self.connection)

        ######### TRANSFORM #########

        df_box["season_player_id"] = df_box[["season_code", "player_id", "team"]].agg("_".join, axis=1).str[1:]
        df_box[["min", "sec"]] = df_box["minutes"].fillna("00:00") \
                                                  .str.replace("DNP", "00:00") \
                                                  .str.split(":", expand=True)
        df_box["min"].replace(r'^\s*$', "00", regex=True, inplace=True)
        df_box["sec"].fillna("00", inplace=True)
        df_box["minutes"] = df_box["min"].astype('float') + df_box["sec"].astype('float') / 60
        df_box["is_playing"].mask(df_box["minutes"] > 0, 1.0, inplace=True)
        df_box = df_box[df_box["dorsal"] != "TOTAL"]

        columns_to_sum = ["is_playing", "is_starter"] + self.table_column_names["players"][7:26]

        for col in columns_to_sum:
            df_box[col] = df_box[col].astype('float')

        df_to_insert = df_box.groupby("season_player_id") \
                             .agg(dict({col: ['first'] for col in ["season_code", "player_id", "player", "team"]},
                                     **{col: ['sum'] for col in columns_to_sum})).reset_index()

        for col in columns_to_sum[2:]:
            df_to_insert[col + "_per_game"] = df_to_insert[col] / df_to_insert["is_playing"]
            df_to_insert[col + "_per_game"] = df_to_insert[col + "_per_game"].round(1)
            if "attempted" in col:
                col_percentage = "_".join(col.split("_")[:2]) + "_percentage"
                df_to_insert[col_percentage] = df_to_insert["_".join(col.split("_")[:2]) + "_made"] / df_to_insert[col]
                df_to_insert[col_percentage] = df_to_insert[col_percentage].round(3)

        df_to_insert["minutes"] = df_to_insert["minutes"].round(1)
        number_of_rows = len(df_to_insert)

        ######### LOAD #########

        # load data on players table (populate all seasons at once)
        for i in range(number_of_rows):

            try:

                data_insert = [str(value) for value in df_to_insert.iloc[i]]
                self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                self.connection.commit()

            except Exception as e:

                print(e, "\nseason_player_id:", df_to_insert.iloc[i]["season_player_id"], "\n")
                
    def extract_and_load_teams(self, sql_insert):

        ######### EXTRACT #########

        query = f"select * from box_score"
        df_box = io_sql.read_sql_query(query, self.connection)

        ######### TRANSFORM #########

        df_box["season_team_id"] = df_box[["season_code", "team"]].agg("_".join, axis=1).str[1:]
        df_box[["min", "sec"]] = df_box["minutes"].fillna("00:00") \
                                                  .str.replace("DNP", "00:00") \
                                                  .str.split(":", expand=True)
        df_box["min"].replace(r'^\s*$', "00", regex=True, inplace=True)
        df_box["sec"].fillna("00", inplace=True)
        df_box["minutes"] = (df_box["min"].astype('float') + df_box["sec"].astype('float') / 60) / 5
        df_box["is_playing"].mask(df_box["minutes"] > 0, 1.0, inplace=True)
        df_box = df_box[df_box["dorsal"] == "TOTAL"]

        columns_to_sum = ["is_playing"] + self.table_column_names["teams"][4:23]

        for col in columns_to_sum:
            df_box[col] = df_box[col].astype('float')

        df_to_insert = df_box.groupby("season_team_id") \
                             .agg(dict({col: ['first'] for col in ["season_code", "team"]},
                                     **{col: ['sum'] for col in columns_to_sum})).reset_index()

        for col in columns_to_sum[1:]:
            df_to_insert[col + "_per_game"] = df_to_insert[col] / df_to_insert["is_playing"]
            df_to_insert[col + "_per_game"] = df_to_insert[col + "_per_game"].round(1)
            if "attempted" in col:
                col_percentage = "_".join(col.split("_")[:2]) + "_percentage"
                df_to_insert[col_percentage] = df_to_insert["_".join(col.split("_")[:2]) + "_made"] / df_to_insert[col]
                df_to_insert[col_percentage] = df_to_insert[col_percentage].round(3)

        df_to_insert["minutes"] = df_to_insert["minutes"].round(1)
        number_of_rows = len(df_to_insert)

        ######### LOAD #########

        # load data on teams table (populate all seasons at once)
        for i in range(number_of_rows):

            try:

                data_insert = [str(value) for value in df_to_insert.iloc[i]]
                self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                self.connection.commit()

            except Exception as e:

                print(e, "\nseason_team_id:", df_to_insert.iloc[i]["season_team_id"], "\n")
                exit()

    def extract_and_load_points(self, season_code, json_success_filenames, json_success_filenames_header, sql_insert):

        ######### EXTRACT & TRANSFORM #########

        # extract data from the json files of header
        df_game_header = h.get_game_header_df(json_success_filenames_header, season_code)
        
        # get the json files of points
        json_success_filenames_points = [filename for filename in json_success_filenames \
                                         if "Points" in filename and filename \
                                         != "E2018_RegularSeason_03_021_20181019_Points.json"]

        # extract data from the json files of points
        for json_filename in json_success_filenames_points:
                          
            start = time()
            
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            
            json_path = fr"../euroleague_json_data/{season_code}/success/{json_filename}"
            json_file = open(json_path)
            json_data = json.load(json_file)
            json_file.close()
            
            df_points = pd.DataFrame(json_data["Rows"])
            number_of_rows = df_points.shape[0]

            point_ids = df_points["NUM_ANOT"]
            game_point_ids = [f"{game_id}_{'{:03d}'.format(point_id)}" for point_id in point_ids]
            df_points.insert(0, "game_id", [game_id for i in range(number_of_rows)])
            df_points.insert(0, "game_point_id", game_point_ids)
            df_points["timestamp"] = pd.to_datetime(df_points["UTC"]).fillna(datetime(1970,1,1))

            # combine data from points and box_score
            df_merged = pd.merge(df_points, df_game_header, how="left", on="game_id").drop(["UTC"], axis=1)
        
            # strip columns that might contain redundant empty spaces
            df_merged = h.strip_points(df_merged)

            # add leading zeros
            df_merged["NUM_ANOT"] = df_merged["NUM_ANOT"].apply(lambda x: '{:03d}'.format(x))
            
            # re-order columns and replace numpy null values (if any) with empty strings
            columns_reordered = ["game_point_id", "game_id", "game", "round", "phase", "season_code"] \
                                + list(df_merged.columns[2:-4])
            df_merged = df_merged[columns_reordered].replace(numpy.nan, "")

            ######### LOAD #########

            # load data on points table (populate per file)
            for i in range(number_of_rows):

                try:
                          
                    data_insert = [value if df_merged.columns[j] == "timestamp" \
                                   else str(value) for j, value in enumerate(df_merged.iloc[i])]
                    self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                    self.connection.commit()

                except Exception as e:

                    print(e, "\ngame_point_id:", df_merged.iloc[i]["game_point_id"], "\n")
                    
    def extract_and_load_play_by_play(self, season_code, json_success_filenames, json_success_filenames_header, sql_insert):

        ######### EXTRACT & TRANSFORM #########

        # extract data from the json files of header
        df_game_header = h.get_game_header_df(json_success_filenames_header, season_code)
        
        # get the json files of play_by_play
        json_success_filenames_play = [filename for filename in json_success_filenames \
                                       if "PlaybyPlay" in filename and filename \
                                       != "E2018_RegularSeason_03_021_20181019_PlaybyPlay.json"]
        
        # extract data from the json files of play_by_play
        for json_filename in json_success_filenames_play:
            
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            
            json_path = fr"../euroleague_json_data/{season_code}/success/{json_filename}"
            json_file = open(json_path)
            json_data = json.load(json_file)
            json_file.close()
            
            quarters = {"FirstQuarter": "q1", "SecondQuarter": "q2", 
                        "ThirdQuarter": "q3", "ForthQuarter": "q4", 
                        "ExtraTime": "extra_time"}
            
            df_play_by_play = h.get_quarters_df(quarters, json_data)   
            number_of_rows = df_play_by_play.shape[0]

            play_ids = df_play_by_play["NUMBEROFPLAY"]
            game_play_ids = [f"{game_id}_{'{:03d}'.format(play_id)}" for play_id in play_ids]
            df_play_by_play.insert(0, "game_id", [game_id for i in range(number_of_rows)])
            df_play_by_play.insert(0, "game_play_id", game_play_ids)

            # combine data from play_by_play and box_score
            df_merged = pd.merge(df_play_by_play, df_game_header, how="left", on="game_id")
    
            # strip columns that might contain redundant empty spaces
            df_merged = h.strip_play_by_play(df_merged)

            # add leading zeros
            df_merged["NUMBEROFPLAY"] = df_merged["NUMBEROFPLAY"].apply(lambda x: '{:03d}'.format(x))
            
           # re-order columns and replace numpy null values (if any) with empty strings
            columns_reordered = ["game_play_id", "game_id", "game", "round", "phase", "season_code"] \
                                + list(df_merged.columns[2:-4])
            df_merged = df_merged[columns_reordered].replace(numpy.nan, "")

            ######### LOAD #########

            # load data on play_by_play table (populate per file)
            for i in range(number_of_rows):

                try:
                          
                    data_insert = [str(value) for value in df_merged.iloc[i]]
                    self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                    self.connection.commit()

                except Exception as e:

                    print(e, "\ngame_play_id:", df_merged.iloc[i]["game_play_id"], "\n")
                
    def extract_and_load_comparison(self, season_code, json_success_filenames, json_success_filenames_header, sql_insert):

        ######### EXTRACT & TRANSFORM #########

        # extract data from the json files of header
        df_game_header = h.get_game_header_df(json_success_filenames_header, season_code)
        
        # get the json files of shooting
        json_success_filenames_shoot = [filename for filename in json_success_filenames \
                                        if "Shooting" in filename and filename \
                                        != "E2018_RegularSeason_03_021_20181019_ShootingGraphic.json"]
        # get the json files of comparison
        json_success_filenames_comp = [filename for filename in json_success_filenames \
                                       if "Comparison" in filename and filename \
                                       != "E2018_RegularSeason_03_021_20181019_Comparison.json"]
        
        # extract data from the json files of shooting
        dfs_shoot = []
        for json_filename in json_success_filenames_shoot:
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            df = pd.read_json(fr"../euroleague_json_data/{season_code}/success/{json_filename}", orient="index").transpose()
            df.insert(0, "game_id", [game_id])   
            dfs_shoot.append(df)           
        df_shoot = pd.concat(dfs_shoot)
        
        # extract data from the json files of comparison
        dfs_comp = []
        for json_filename in json_success_filenames_comp:
            game_code = json_filename.split("_")[3]
            game_id = f"{season_code.strip('E')}_{game_code}"
            df = pd.read_json(fr"../euroleague_json_data/{season_code}/success/{json_filename}", orient="index")\
                   .transpose().drop(["minutoActual", "isLive"], axis=1)
            df.insert(0, "game_id", [game_id])
            dfs_comp.append(df)         
        df_comp = pd.concat(dfs_comp)

        # combine data from shooting, comparison and header
        df_merged = pd.merge(df_shoot, df_comp, how="outer", on="game_id")
        df_merged = pd.merge(df_merged, df_game_header, how="left", on="game_id")
        
        # get the number of rows of the dataframe
        number_of_rows = df_merged.shape[0]
        
        # strip columns that might contain redundant empty spaces
        df_merged = h.strip_comparison(df_merged)

        # re-order columns and replace numpy null values (if any) with empty strings
        columns_reordered = ["game_id", "game", "round", "phase", "season_code"] \
                            + list(df_merged.columns[1:-4])
        df_merged = df_merged[columns_reordered].replace(numpy.nan, "")

        ######### LOAD #########

        # load data on comparison table (populate per season)
        for i in range(number_of_rows):

            try:
                
                data_insert = [str(value) for value in df_merged.iloc[i]]
                self.cursor.execute(sql_insert.as_string(self.connection), (data_insert))
                self.connection.commit()

            except Exception as e:

                print(e, "\ngame_id:", df_merged.iloc[i]["game_id"], "\n")
