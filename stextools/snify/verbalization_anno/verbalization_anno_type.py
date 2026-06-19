from typing import Optional
import re
import functools

from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs
from stextools.snify.annotype import AnnoType, StateType, StepperStatus
from stextools.snify.objective_anno.objective_anno_state import ObjectiveAnnoState
from stextools.snify.snify_commands import SkipCommand
from stextools.stepper.command import CommandCollection, Command, CommandInfo, CommandOutcome
from stextools.stepper.document import Document, STeXDocument
from stextools.stepper.document_stepper import TextRewriteOutcome, SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, UndoCommand, RedoCommand



# python -m stextools snify --mode=text,verbalizations "C:\Users\ivana\Desktop\MathHub\smglom\ai-agents\source\mod\search-based-agent.en.tex"

#control the doublon
# add

@functools.cache
def get_stex_catalogs() -> dict[str, LocalFlamsCatalog]:
    return local_flams_stex_catalogs()

class VerbalizationAnnoState:
    pass


class AddVerbalizationCommand(Command):
    def __init__(self, position: int, symbol_name:str, document_content:str):
        self.position = position
        self.symbol_name= symbol_name
        #self.snify_state = snify_state
        self.document_content = document_content
        super().__init__(CommandInfo(
            pattern_presentation='a',
            description_short='dd verbalization',
            description_long='Add a verbalization for the current \\symdef.'
        ))

    def execute(self, call: str) -> list[CommandOutcome]:
        """ this is called when the user presses 'a' """
        
        #specifications     
        interface.write_text('\nPlease enter the specifications of the verbalization you want to add: ')
        specifications = interface.get_input()
        num_arguments= len(re.findall(r'#\d+', specifications))
        
        

# python -m stextools snify --mode=text,verbalizations "C:\Users\ivana\Desktop\MathHub\ai-agents\source\mod\utility-based-agent.en.tex"

        #annotation type
        pos = [i for i, char in enumerate(specifications)
               if char==':']
        letter=  specifications[pos[-1]+1]
        if num_arguments== 1:
            annotation_type= letter.upper()
        else:
            annotation_type= letter.upper() + str(num_arguments)
        interface.write_text(f'is the annotation type {annotation_type} ? write y/n: ')
        answ= interface.get_input()
        if answ == "n" :
            interface.write_text ('\nPlease enter the right annotation type: ')
            annotation_type= interface.get_input()

        

        # name #1 total:A function:N from #2 to #3
        spec= re.sub(r'#\d+', '', specifications)
        spec= re.sub(r':[A-Za-z]+', '', spec)
        words= spec.split()
        name = "-".join(words)

        #args
        while True:
            interface.write_text ('\nDo you need to enter the type of each argument c/d?\n Please answer with y/n:  ')
            ans_args= interface.get_input()
            if ans_args in ("y","n"):
                break
            interface.write_text("Please answer with y or n.\n")
            
        args=""
        if ans_args== "y":
            while True:
                interface.write_text ('please enter c/d for each argument that we have in the specifications: ')
                entered_args= interface.get_input()

                if (all( ch in "cd" for ch in entered_args) and len(entered_args)==num_arguments ):
                    args = entered_args
                    break
                interface.write_text ('please enter exactly '+str(num_arguments) + ' character(s) consisting only of c and/or d.\n')
        optional=  f'[Name={name}]' if not args else f'[Name={name}, args={args}]'  

     
            # control the duplicates
        if (f'\\verbalization{{{self.symbol_name}}}{optional}{{{annotation_type}}}{{{specifications}}}\n') in self.document_content:
            interface.write_text("This verbalization already exist.\n")   
            return[]  
        else:

            return [
                SubstitutionOutcome(
                    f'\\verbalization{{{self.symbol_name}}}{optional}{{{annotation_type}}}{{{specifications}}}\n',
                    self.position, self.position
                )
            ]
        
# python -m stextools snify --mode=text,verbalizations "C:\Users\ivana\Desktop\MathHub\smglom\ai-agents\source\mod\search-based-agent.en.tex"

class DeleteVerbalizationCommand(Command):
    def __init__(self, position: int, symbol_name:str, document_content:str):
        self.position = position
        self.symbol_name= symbol_name
        self.document_content = document_content
        super().__init__(CommandInfo(
            pattern_presentation='d',
            description_short='elete verbalization',
            description_long='Delete a verbalization for the current \\symdef.'
        ))
    def execute(self, call: str) -> list[CommandOutcome]:
        """ this is called when the user presses 'd' """
        pattern = rf'\\verbalization\{{{re.escape(self.symbol_name)}\}}\[.*?\]\{{.*?\}}\{{.*?\}}'
        matches = list (re.finditer(pattern, self.document_content))

        if not matches:
            interface.write_text(f'No Verbalizations found for "{self.symbol_name}".\n'
                    )
            return []
        
        interface.write_text(f' Existing verbalization for "{self.symbol_name}": \n')

        for i, match in enumerate(matches, start =1):
            interface.write_text(f"{i}) {match.group(0)}\n"         
            )

        interface.write_text("\nwhich verbalization do you want to delete: \n")
        answer= interface.get_input()
        
     
        try:
            choice = int (answer)
            selected_match= matches[choice - 1]
        except (ValueError, IndexError):
            interface.write_text('\nInvalid choice.\n')
            return[]
        

        return[ SubstitutionOutcome('', selected_match.start(), selected_match.end())]
    

class VerbalizationAnnoType(AnnoType[VerbalizationAnnoState]):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return f'verbalization-anno'

    def is_applicable(self, document: Document) -> bool:
        if 'verbalizations' not in self.snify_state.mode:
            return False
        if isinstance(document, STeXDocument):
            return True
        else:
            return False

    def get_initial_state(self) -> StateType:
        get_stex_catalogs()
        return VerbalizationAnnoState()

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        # a string with the content of the file
        document_content = document.get_content()
        # we only care about stuff after the current position
        document_content = document_content[position:]

        our_position = document_content.find('\\symdef')
        if our_position == -1:    # we did not find anything
            return None
        else:
            return our_position + position, []

    def show_current_state(self):
        interface.clear()
        interface.write_text('\nHELLO, I AM THE VERBALIZATION ASSISTANT\n')

        document_content = self.snify_state.get_current_document().get_content()
        position = self.snify_state.cursor.in_doc_pos

        string = document_content[position:]
        line = string.splitlines()[0]

        interface.write_text('\nCurrent \\symdef:\n\n')
        interface.show_code(line, format='sTeX')

        match = re.search(r'\\symdef\{([^}]*)\}', line)
        symbol_name = match.group(1) if match else 'UNKNOWN'
        pattern = rf'\\verbalization\{{{re.escape(symbol_name)}\}}\[.*?\]\{{.*?\}}\{{.*?\}}'
        matches = list (re.finditer(pattern, document_content))

        catalog = get_stex_catalogs()['en']  # english catalog
        for symbol in catalog.symb_iter():
            if symbol.uri.endswith('s=' + symbol_name):
                for verbalization in catalog.symb_to_verb[symbol]:
                    print('I found ' + verbalization.verb)

        if not matches:
            interface.write_text(f'\nNo Verbalizations found for "{symbol_name}".\n'
                    )
            return []
        
        interface.write_text(f'\n Existing verbalizations for "{symbol_name}": \n')

        for i, match in enumerate(matches, start =1):
            interface.write_text(f"{i}) {match.group(0)}\n"         
            )
        

    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        position = self.snify_state.cursor.in_doc_pos
        document_content = self.snify_state.get_current_document().get_content()
        string = document_content[position:]

        line= string.splitlines()[0]

        match = re.search(r'\\symdef\{([^}]*)\}' , line)
        symbol_name = match.group(1) if match else 'UNKNOWN'
        AddVerbalizationCommand(position, symbol_name, document_content)
        position = position + 1 + string.find('\n')

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state, description_short='kip'),
                AddVerbalizationCommand(position, symbol_name, document_content),
                DeleteVerbalizationCommand(position, symbol_name, document_content),
            ],
            have_help=True,
        )
