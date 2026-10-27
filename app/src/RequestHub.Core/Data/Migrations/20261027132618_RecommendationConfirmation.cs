using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RequestHub.Core.Data.Migrations
{
    /// <inheritdoc />
    public partial class RecommendationConfirmation : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "ConfirmedById",
                table: "Recommendations",
                type: "character varying(80)",
                maxLength: 80,
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_Recommendations_ConfirmedById",
                table: "Recommendations",
                column: "ConfirmedById");

            migrationBuilder.AddForeignKey(
                name: "FK_Recommendations_Users_ConfirmedById",
                table: "Recommendations",
                column: "ConfirmedById",
                principalTable: "Users",
                principalColumn: "Id",
                onDelete: ReferentialAction.Restrict);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_Recommendations_Users_ConfirmedById",
                table: "Recommendations");

            migrationBuilder.DropIndex(
                name: "IX_Recommendations_ConfirmedById",
                table: "Recommendations");

            migrationBuilder.DropColumn(
                name: "ConfirmedById",
                table: "Recommendations");
        }
    }
}
