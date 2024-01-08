*** Settings ***
Library     ./common_lib/libraries/discovery.py    WITH NAME    Discovery
Library     String


*** Variables ***
${settings_board1}      ${EMPTY}
${settings_board2}      ${EMPTY}

*** Keywords ***
Get Boards
    [Arguments]    ${allow_many}=${True}    ${allow_list}=[]    ${minimum_boards}=1

    # Delay in case boards are re-enumerating over USB
    Sleep    ${2}

    @{boards}=    Discovery.Get Connected Boards    ${allow_list}
    ${num_boards}=    Get Length    ${boards}
    Log    ${num_boards} boards found!

    IF    ${num_boards} < ${minimum_boards}    Fail    Minimum number of boards (${minimum_boards}) not found

    IF    ${num_boards} >= ${1}
        Set Global Variable    ${settings_board1}    ${boards[0]}
    END
    
    IF    ${num_boards} > ${1}
        IF    ${allow_many} == ${False}
            Fail    Please ensure only one board is connected!
        END
        Set Global Variable    ${settings_board2}    ${boards[1]}
    END

Init Board
    [Arguments]    ${board}

    IF    ${board.is_initialized} == ${False}
        Call Method    ${board}    open_and_init_board
        IF    ${board.is_initialized} == ${False}
            Fail    Board is not ready
        END
    END
    # For all automated testing, upload an empty boot.py to the board to
    # prevent the default script from running.
    Upload Script to Board    ${board}    common_lib/scripts/empty_boot.py    boot.py
    Board Reset Module    ${board}
    ${resp}=    Call Method    ${board.python_uart}    send    import os
    ${resp}=    Call Method    ${board.python_uart}    send    import sys

De-Init Board
    [Arguments]    ${board}
    IF    ${board.is_initialized} == ${True}
        Call Method    ${board}    close_ports_and_reset
    END

Switch Board to Raw REPL
    [Arguments]    ${board}
    ${resp}=    Call Method    ${board}    close_repl_uart
    ${resp}=    Call Method    ${board}    open_raw_repl_uart

Switch Board to User REPL
    [Arguments]    ${board}

    ${resp}=    Call Method    ${board}    close_raw_repl_uart
    ${resp}=    Call Method    ${board}    open_repl_uart

Run Script on Board
    [Documentation]    Run a script on the board and return the output. This uses raw REPL.
    [Arguments]    ${board}    ${script}

    Switch Board to Raw REPL    ${board}
    ${resp}=    Call Method    ${board.python_raw_repl_uart}    execfile    ${script}
    Switch Board to User REPL    ${board}
    RETURN    ${resp}

Get Board Device ID
    [Documentation]    Get the device ID of the board.
    [Arguments]    ${board}
    ${resp}=    Call Method    ${board.python_uart}    send    import machine
    ${resp}=    Call Method    ${board.python_uart}    send    import binascii
    ${resp}=    Call Method    ${board.python_uart}    send    binascii.hexlify(machine.unique_id()).decode()
    ${id}=    Replace String    ${resp}    '    ${EMPTY}
    RETURN    ${id}

Upload Script to Board
    [Documentation]    Uses raw REPL to upload a script to the board and save it to the file system.
    [Arguments]    ${board}    ${src_script}    ${dst_script}

    Switch Board to Raw REPL    ${board}
    ${resp}=    Call Method    ${board}    upload_py_file    ${src_script}    ${dst_script}
    Switch Board to User REPL    ${board}

User REPL Send
    [Documentation]    Send a command using the board's user REPL interface.
    [Arguments]    ${board}    ${cmd}    ${timeout}=${1.0}

    ${resp}=    Call Method    ${board.python_uart}    send    ${cmd}    ${timeout}

    RETURN    ${resp}

Raw REPL Exec
    [Documentation]    Execute a command using the board's raw REPL interface.
    [Arguments]    ${board}    ${cmd}

    ${resp}=    Call Method    ${board.python_raw_repl_uart}    exec    ${cmd}

    RETURN    ${resp}

Zephyr Shell Send
    [Documentation]    Send a command using the board's Zephyr shell interface.
    [Arguments]    ${board}    ${cmd}    ${timeout}=${1.0}

    ${resp}=    Call Method    ${board.zephyr_uart}    send    ${cmd}    ${timeout}

    RETURN    ${resp}

DUT1 User REPL Send
    [Arguments]    ${cmd}    ${timeout}=${1.0}

    ${resp}=    User REPL Send    ${settings_board1}    ${cmd}    ${timeout}

    RETURN    ${resp}

Board Reset Module
    [Arguments]    ${board}

    Call Method    ${board}    reset_module

Board Terminate Script
    [Arguments]    ${board}

    Call Method    ${board}    quit_running_app
    Sleep    100ms

Board Delete Script
    [Arguments]    ${board}    ${script}

    ${resp}=    User REPL Send    ${board}    import os
    ${resp}=    User REPL Send    ${board}    os.unlink('${script}')

Board Soft Reboot
    [Arguments]    ${board}

    ${resp}=    Call Method    ${board}    soft_reset_module

    RETURN    ${resp}
