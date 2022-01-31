import argparse
import logging
import bibtexparser
import pathlib
import os
#from os import path, listdir, scandir
import pdf2bib
#import itertools
#import pkgutil
import pdfrenamer.config as config
from pdfrenamer.filename_creators import build_filename, AllowedTags, check_format_is_valid
import traceback
import sys

logger = logging.getLogger("pdf-renamer")

def rename(target, format=None, tags=None):
    '''
    This is the main routine of the script. When the library is used as a command-line tool (via the entry-point "pdfrenamer") the input arguments
    are collected, validated and sent to this function (see the function main () below). 
    The function tries to rename the pdf file whose path is specified in the input argument target with the format specified in the input 
    argument format. The info of the paper (title, authors, etc.) are obtained via the library pdf2bib (which in turns uses pdf2doi). 
    If the input argument target is the path of a folder, the function is applied to each pdf file contained in the folder
    (by calling again the same function). If the global settingcheck_subfolders is set to True, it also renames pdf files in all subfolders (recursively).

    Parameters
    ----------
    target : string
        Relative or absolute path of the target .pdf file or directory
    Returns
    -------
    results, dictionary or list of dictionaries (or None if an error occured)
        The output is a single dictionary if target is a file, or a list of dictionaries if target is a directory, 
        each element of the list describing one file. Each dictionary has the following keys
        result['path_original']     = path of the pdf file (with the original filename)
        result['path_new']          = path of the pdf file, with the new filename, or None if it was not possible to generate a new filename
        result['identifier']        = DOI or other identifier (or None if nothing is found)
        result['identifier_type']   = String specifying the type of identifier (e.g. 'doi' or 'arxiv')
        result['validation_info']   = Additional info on the paper. If config.get('webvalidation') = True, then result['validation_info']
                                      will typically contain raw bibtex data for this paper. Otherwise it will just contain True 
        result['path']              = Path of the pdf file
        result['method']            = Method used by pdf2doi to find the identifier
        result['metadata']          = Dictionary containing bibtex info
        result['bibtex']            = A string containing a valid bibtex entry

    '''
    
    # Setup logging
    logger = logging.getLogger("pdf-renamer")

    if not format: format = config.get('format')
    
    #Make some sanity check on the format, and extract tags
    if not tags:    #If tags is a valid variable, it means the format was already checked earlier (i.e. this call to the function rename was generated by
                    #an earlier call to the function rename. By not checking again the format, we save time
        tags = check_format_is_valid(format)
        if tags == None: #if the function check_format_is_valid has returned, then the format is not valid and the function terminates
            return None

    #Check if path is valid
    if not(os.path.exists(target)):
        logger.error(f"{target} is not a valid path to a file or a directory.")
        return
    
    #Check if target is a directory
        # If yes, we look for all the .pdf files inside it, and for each of them
        # we call again this function by passing the file path as target.
        #
        # Moreover, if config.get('check_subfolders')==True, for each subfolder in the directory we call again this function
        # by passsing the subfolder as target

    if  os.path.isdir(target):
        logger.info(f"Looking for pdf files and subfolders in the folder {target}...")
        if not(target.endswith(os.path.sep)): #Make sure the path ends with "\" or "/" (according to the OS)
                target = target + os.path.sep

        #We build a list of all the pdf files in this folder, and of all subfolders
        pdf_files = [f for f in os.listdir(target) if (f.lower()).endswith('.pdf')]
        subfolders = [ f.path for f in os.scandir(target) if f.is_dir() ]

        numb_files = len(pdf_files)
        if numb_files == 0:
            logger.error("No pdf file found in this folder.")
        else:
            logger.info(f"Found {numb_files} pdf file(s).")

            files_processed = [] #For each pdf file in the target folder we will store a dictionary inside this list
            for f in pdf_files:
                logger.info(f"................") 
                file = target + f
                #We call again this same function but this time targeting the single file
                result = rename(file, format=format, tags=tags)
                files_processed.append(result)
            logger.info("................") 

        #If there are subfolders, and if config.get('check_subfolders')==True, we call gain this function for each subfolder
        numb_subfolders = len(subfolders)
        if numb_subfolders:
            logger.info(f"Found {numb_subfolders} subfolder(s)")
            if config.get('check_subfolders')==True :
                logger.info("Exploring subfolders...") 
                for subfolder in subfolders:
                    result = rename(subfolder, format=format,tags=tags)
                    files_processed.extend(result)
            else:
                logger.info("The subfolder(s) will not be scanned because the parameter check_subfolders is set to False."+
                            " When using this script from command line, use the option -sf to explore also subfolders.") 
            logger.info("................") 
        return files_processed
    
    #If target is not a directory, we check that it is an existing file and that it ends with .pdf
    else:
        filename = target
        logger.info(f"File: {filename}")  
        if not os.path.exists(filename):
            logger.error(f"'{filename}' is not a valid file or directory.")
            return None    
        if not (filename.lower()).endswith('.pdf'):
            logger.error("The file must have .pdf extension.")
            return None
        
        #We use the pdf2bib library to retrieve info of this file
        logger.info(f"Calling the pdf2bib library to retrieve the bibtex info of this file.")
        try:
            result = pdf2bib.pdf2bib_singlefile(filename)
            result['path_original'] = filename

            #if pdf2bib was able to find an identifer, and thus to retrieve the bibtex data, we use them to rename the file
            if result['metadata'] and result['identifier']:
                logger.info(f"Found bibtex data and an identifier for this file: {result['identifier']} ({result['identifier_type']}).")
                metadata = result['metadata'].copy()
                metadata_string = "\n\t"+"\n\t".join([f"{key} = \"{metadata[key]}\"" for key in metadata.keys()] ) 
                logger.info("Found the following data:" + metadata_string)

                #Generate the new name by calling the function build_filename
                NewName = build_filename(metadata, format, tags)
                ext = os.path.splitext(filename)[-1].lower() #Extract the file extension from the old file name
                directory = pathlib.Path(filename).parent
                NewPath = str(directory) + os.path.sep + NewName
                NewPathWithExt = NewPath + ext
                logger.info(f"The new file name is {NewPathWithExt}")
                if (filename==NewPathWithExt):
                    logger.info("The new file name is identical to the old one. Nothing will be changed")
                    result['path_new'] = NewPathWithExt
                else:
                    try:
                        NewPathWithExt_renamed = rename_file(filename,NewPath,ext) 
                        logger.info(f"File renamed correctly.")
                        if not (NewPathWithExt == NewPathWithExt_renamed):
                            logger.info(f"(Note: Another file with the same name was already present in the same folder, so a numerical index was added at the end).")
                        result['path_new'] = NewPathWithExt_renamed
                    except Exception as e: 
                        logger.error('Some error occured while trying to rename this file: \n '+ str(e))
                        result['path_new'] = None
            else:
                logger.info("The pdf2doi library was not able to find an identifier for this pdf file.")
                result['path_new'] = None
        except Exception as e: 
            print(traceback.format_exc())
            # or
            print(sys.exc_info()[2])
            logger.error('Some unexpected error occured while using pdf2bib to process this file: \n '+ str(e))
            result['path_new'] = None

        return result 

def rename_file(old_path,new_path,ext):
    #It attempts to rename the file in old_path with the new name contained in new_path. 
    #If another file with the same name specified by new_path already exists in the same folder, it adds an 
    #incremental number (e.g. "filename.pdf" becomes "filename (2).pdf")

    if not os.path.exists(old_path):
        raise ValueError(f"The file {old_path} does not exist")
    i=1
    while True:
        New_path = new_path + (f" ({i})" if i>1 else "") + ext
        if os.path.exists(New_path):
            i = i+1
            continue
        else:
            os.rename(old_path,New_path)
            return New_path

def add_abbreviations(path_abbreviation_file):
    #Adds the content of the text file specified by the path path_abbreviation_file at the beginning of the file UserDefinedAbbreviations.txt
    if not(os.path.exists(path_abbreviation_file)):
        logger.error(f"{path_abbreviation_file} is not a valid path to a file.")
        return

    logger.info(f"Loading the file {path_abbreviation_file}...")
    try:
        with open(path_abbreviation_file, 'r') as new_abbreviation_file:
            new_abbreviation = new_abbreviation_file.read()
    except Exception as e: 
        logger.error('Some error occured while loading this file: \n '+ str(e))
        return

    logger.info(f"Adding the content of the file {path_abbreviation_file} to the user-specified journal abbreviations...")

    try:
        path_current_directory = os.path.dirname(__file__)
        path_UserDefinedAbbreviations = os.path.join(path_current_directory, 'UserDefinedAbbreviations.txt')
        with open(path_UserDefinedAbbreviations, 'r') as UserDefinedAbbreviations_oldfile:
            UserDefinedAbbreviations_old = UserDefinedAbbreviations_oldfile.read()
        with open(path_UserDefinedAbbreviations, 'w') as UserDefinedAbbreviations_newfile:
            UserDefinedAbbreviations_newfile.write( new_abbreviation )
            UserDefinedAbbreviations_newfile.write('\n')
            UserDefinedAbbreviations_newfile.write( UserDefinedAbbreviations_old )
    except Exception as e: 
        logger.error('Some error occured: \n '+ str(e))
        return

    logger.info(f"The new journal abbreviations were correctly added.")


def main():
    parser = argparse.ArgumentParser( 
                                    description = "Automatically renames pdf files of scientific publications by retrieving their identifiers (e.g. DOI or arxiv ID) and looking up their bibtex infos.",
                                    epilog = "",
                                    formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
                        "path",
                        help = "Relative path of the pdf file or of a folder.",
                        metavar = "path",
                        nargs = '*')
    parser.add_argument("-s",
                        "--decrease_verbose",
                        help="Decrease verbosity. By default (i.e. when not using -s), all steps performed by pdf-renamer, pdf2dbib and pdf2doi are documented.",
                        action="store_true")
    parser.add_argument('-f', 
                        help=f"Format of the new filename. Default = \"{config.get('format')}\".\n"+
                        "Valid tags:\n"+
                        "\n".join([key+val for key,val in AllowedTags.items()]),
                        action="store", dest="format", type=str, default=config.get('format'))
    parser.add_argument("-sf",
                        "--sub_folders",
                        help=f"Rename also pdf files contained in subfolders of target folder. Default = \"{config.get('check_subfolders')}\".",
                        action="store_true")
    parser.add_argument('-max_length_authors', 
                        help=f"Sets the maximum length of any string related to authors (default={str(config.get('max_length_authors'))}).",
                        action="store", dest="max_length_authors", type=int, default=config.get('max_length_authors'))
    parser.add_argument('-max_length_filename', 
                        help=f"Sets the maximum length of any generated filename. Any filename longer than this will be truncated (default={str(config.get('max_length_filename'))}).",
                        action="store", dest="max_length_filename", type=int, default=config.get('max_length_filename'))
    parser.add_argument(
                        "-add_abbreviation_file",
                        help="The content of the text file specified by PATH_ABBREVIATION_FILE will be added to the user list of journal abbreviations.\n"+
                        "Each row of the text file must have the format \'FULL NAME = ABBREVIATION\'.",
                        action="store", dest="path_abbreviation_file", type=str)
    parser.add_argument(
                        "-sd",
                        "--set_default",
                        help="By adding this command, any value specified (in this same command) for the filename format (-f), "+
                        "max length of author string (-max_length_authors), max length of filename string (-max_length_filename) "+
                        "will be also stored as default value(s) for the future.",
                        action="store_true")
    parser.add_argument("-install--right--click",
                        dest="install_right_click",
                        action="store_true",
                        help="Add a shortcut to pdf-renamer in the right-click context menu of Windows. You can rename a single pdf file (or all pdf files in a folder) by just right clicking on it! NOTE: this feature is only available on Windows.")
    parser.add_argument("-uninstall--right--click",
                        dest="uninstall_right_click",
                        action="store_true",
                        help="Uninstall the right-click context menu functionalities. NOTE: this feature is only available on Windows.")

    
    args = parser.parse_args()

    # Setup logging
    config.set('verbose',not(args.decrease_verbose)) #store the desired verbose level in the global config of pdf-renamer. This will also automatically update the pdf2bib and pdf2doi logger level.
    logger = logging.getLogger("pdf-renamer")

    #If the command -install--right--click was specified, it sets the right keys in the system registry
    if args.install_right_click:
        config.set('verbose',True)
        import pdfrenamer.utils_registry as utils_registry
        utils_registry.install_right_click()
        return
    if args.uninstall_right_click:
        config.set('verbose',True)
        import pdfrenamer.utils_registry as utils_registry
        utils_registry.uninstall_right_click()
        return

    if args.path_abbreviation_file:
        add_abbreviations(args.path_abbreviation_file)
        return

    if (check_format_is_valid(args.format)):
        config.set('format' , args.format)
    if (isinstance(args.max_length_authors,int) and args.max_length_authors>0):
        config.set('max_length_authors' , args.max_length_authors)
    else:
        logger.error(f"The specified value for max_length_authors is not valid.")
    if (isinstance(args.max_length_filename,int) and args.max_length_filename>0):
        config.set('max_length_filename' , args.max_length_filename)
    else:
        logger.error(f"The specified value for max_length_filename is not valid.")
    config.set('check_subfolders' , args.sub_folders)

    if args.set_default:
        logger.info("Storing the settings specified by the user (if any is valid) as default values...")
        config.WriteParamsINIfile()
        logger.info("Done.")

    ## The following block of code (until ##END) is required to make sure that 'path' is considered a required parameter, except for the case when
    ## -install--right--click or -uninstall--right--click are used, or when the user is setting default values for some of the parameters
    if isinstance(args.path,list):
        if len(args.path)>0:
            target = args.path[0]
        else:
            target = ""
    else:
        target = args.path
    if target == "" and not (args.set_default):
        print("pdfrenamer: error: the following arguments are required: path. Type \'pdfrenamer --h\' for a list of commands.")
    if target == "": #This occurs either if the user forgot to add a target, or if the user used the -sd command to set default values
        return
    ## END

    if(args.decrease_verbose==True):
        print(f"(All intermediate output will be suppressed. To see additional outuput, do not use the command -s)")
    results = rename(target=target)

    if results==None:  #This typically happens when target is neither a valid file nor a valid directory. In this case we stop
        return         #the script execution here. Proper error messages were raised by the rename function

    if  os.path.isdir(target):
        target = os.path.join(target, '') #This makes sure that, if target is a path to a directory, it has the ending "/" or "\"
    MainPath = os.path.dirname(target) #Extract the path of target. If target is a directory, then MainPath = target

    from colorama import init,Fore, Back, Style
    init(autoreset=True)
    print(Fore.RED + "Summaries of changes done:")

    if not isinstance(results,list):
        results = [results]
    
    counter = 0
    counter_identifier_notfound = 0

    for result in results:
        if result and result['identifier'] and result['path_new']:
            if not(result['path_original']==result['path_new']):
                print(Fore.YELLOW + f"{os.path.relpath(result['path_original'],MainPath)}")
                print(Fore.MAGENTA + f"---> {os.path.relpath(result['path_new'],MainPath)}")
                counter = counter + 1
        else : 
            counter_identifier_notfound = counter_identifier_notfound + 1

    if counter==0:
        print("No file has been renamed.")
    else:
        print(f"{counter} file" + ("s have " if counter>1 else " has ") + "been renamed.")

    if counter_identifier_notfound > 0:
        print(Fore.RED +"The following pdf files could not be renamed because it was not possile to automatically find " +
              "the publication identifier (DOI or arXiv ID). Try to manually add a valid identifier to each file via " +
              "the command \"pdf2doi 'filename.pdf' -id 'valid_identifier'\" and then run again pdf-renamer.")  
        for result in results:
            if not(result['identifier']):
                print(f"{result['path_original']}")
    return

if __name__ == '__main__':
    main()